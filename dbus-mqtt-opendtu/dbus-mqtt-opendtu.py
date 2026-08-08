#!/usr/bin/env python

from gi.repository import GLib  # pyright: ignore[reportMissingImports]
import configparser
import json
import logging
import os
import platform
import re
import sys
from time import sleep, time

import dbus  # pyright: ignore[reportMissingImports]

# import external packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext"))
import paho.mqtt.client as mqtt  # noqa: E402

# import Victron Energy packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext", "velib_python"))
from vedbus import VeDbusService  # noqa: E402
from ve_utils import get_vrm_portal_id  # noqa: E402


FIRMWARE_VERSION = "0.2.0-opendtu"
DEFAULT_BASE_TOPIC = "solar"
DEFAULT_INVERTER_TIMEOUT = 300
DEFAULT_POSITION = 0
DEFAULT_MAX_POWER = 100000
FIRST_DEVICE_INSTANCE = 100
INVERTER_SERIAL_RE = re.compile(r"^\d{8,}$")

config = None
manager = None
mqtt_client = None


def load_config():
    config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.ini")
    if not os.path.exists(config_file):
        print(
            'ERROR:The "%s" is not found. Did you copy or rename the "config.sample.ini" to "config.ini"? '
            "The driver restarts in 60 seconds." % config_file
        )
        sleep(60)
        sys.exit()

    parser = configparser.ConfigParser()
    parser.read(config_file)

    if "MQTT" not in parser:
        print('ERROR:The "config.ini" must contain an [MQTT] section. The driver restarts in 60 seconds.')
        sleep(60)
        sys.exit()

    if parser["MQTT"].get("broker_address", "") in ("", "IP_ADDR_OR_FQDN"):
        print('ERROR:The "config.ini" is using an invalid broker_address. The driver restarts in 60 seconds.')
        sleep(60)
        sys.exit()

    return parser


def setup_logging():
    logging.basicConfig(level=logging.WARNING)


def base_topic():
    return config["MQTT"].get("base_topic", DEFAULT_BASE_TOPIC).strip("/")


def opendtu_topic():
    return "%s/#" % base_topic()


def command_topic(serial):
    return "%s/%s/cmd/limit_nonpersistent_absolute" % (base_topic(), serial)


def sanitize_service_suffix(value):
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", value)
    suffix = suffix.strip("_")
    return suffix or "unknown"


def service_name_for_serial(serial):
    return "com.victronenergy.pvinverter.mqtt_%s" % sanitize_service_suffix(serial)


def device_instance_map_file():
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "device_instances.json")


def load_device_instance_map():
    path = device_instance_map_file()
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except Exception as err:
        logging.warning("Could not read device instance map %s: %s", path, err)
        return {}

    instances = {}
    for serial, value in data.items():
        if INVERTER_SERIAL_RE.match(serial):
            try:
                instances[serial] = int(value)
            except (TypeError, ValueError):
                logging.warning("Ignoring invalid stored DeviceInstance for %s: %s", serial, value)
    return instances


def save_device_instance_map(instances):
    path = device_instance_map_file()
    try:
        with open(path, "w") as handle:
            json.dump(instances, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception as err:
        logging.warning("Could not write device instance map %s: %s", path, err)


def used_device_instances():
    used = set()
    try:
        bus = dbus.SystemBus()
        bus_object = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
        bus_iface = dbus.Interface(bus_object, "org.freedesktop.DBus")
        for service_name in bus_iface.ListNames():
            service_name = str(service_name)
            if not service_name.startswith("com.victronenergy."):
                continue
            if service_name.startswith("com.victronenergy.pvinverter.mqtt_"):
                continue

            try:
                device = bus.get_object(service_name, "/DeviceInstance")
                item = dbus.Interface(device, "com.victronenergy.BusItem")
                used.add(int(item.GetValue()))
            except Exception:
                pass
    except Exception as err:
        logging.warning("Could not scan existing D-Bus DeviceInstance values: %s", err)

    return used


def text_kwh(path, value):
    return "" if value is None else "%.2fkWh" % value


def text_a(path, value):
    return "" if value is None else "%.1fA" % value


def text_w(path, value):
    return "" if value is None else "%iW" % value


def text_v(path, value):
    return "" if value is None else "%.2fV" % value


def text_hz(path, value):
    return "" if value is None else "%.2fHz" % value


def text_pf(path, value):
    return "" if value is None else "%.3f" % value


def text_n(path, value):
    return "" if value is None else "%i" % value


def parse_payload(payload):
    if payload in ("", b""):
        raise ValueError("empty payload")

    decoded = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
    try:
        return json.loads(decoded)
    except ValueError:
        return decoded


def parse_float_payload(payload):
    parsed = parse_payload(payload)

    if isinstance(parsed, dict):
        if "value" in parsed:
            return float(parsed["value"])
        raise ValueError("payload object does not contain value")

    return float(parsed)


def parse_text_payload(payload):
    parsed = parse_payload(payload)
    if isinstance(parsed, dict):
        if "value" in parsed:
            return str(parsed["value"])
        raise ValueError("payload object does not contain value")
    return str(parsed)


class OpenDtuInverterService:
    def __init__(self, serial, deviceinstance):
        self.serial = serial
        self.last_seen = int(time())
        self.name = None
        self.power = 0.0
        self._dbusservice = VeDbusService(
            service_name_for_serial(serial),
            register=False,
        )

        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path(
            "/Mgmt/ProcessVersion",
            "Unknown version, and running on Python " + platform.python_version(),
        )
        self._dbusservice.add_path("/Mgmt/Connection", "OpenDTU MQTT %s" % serial)

        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 0xFFFF)
        self._dbusservice.add_path("/ProductName", "OpenDTU PV Inverter")
        self._dbusservice.add_path("/CustomName", "OpenDTU %s" % serial)
        self._dbusservice.add_path("/FirmwareVersion", FIRMWARE_VERSION)
        self._dbusservice.add_path("/Serial", serial)
        self._dbusservice.add_path("/Connected", 1)

        self._dbusservice.add_path("/Latency", None)
        self._dbusservice.add_path("/ErrorCode", 0)
        self._dbusservice.add_path("/Position", DEFAULT_POSITION)
        self._dbusservice.add_path("/StatusCode", 8)
        self._dbusservice.add_path("/UpdateIndex", 0, gettextcallback=text_n)

        self._dbusservice.add_path("/Ac/Power", 0, gettextcallback=text_w)
        self._dbusservice.add_path("/Ac/Current", None, gettextcallback=text_a)
        self._dbusservice.add_path("/Ac/Voltage", None, gettextcallback=text_v)
        self._dbusservice.add_path("/Ac/Energy/Forward", None, gettextcallback=text_kwh)
        self._dbusservice.add_path(
            "/Ac/MaxPower",
            DEFAULT_MAX_POWER,
            gettextcallback=text_w,
            writeable=True,
            onchangecallback=self._handle_max_power_changed,
        )
        self._dbusservice.add_path("/Ac/Position", DEFAULT_POSITION, gettextcallback=text_n)
        self._dbusservice.add_path("/Ac/StatusCode", 8, gettextcallback=text_n)

        self._dbusservice.add_path("/Ac/L1/Power", 0, gettextcallback=text_w)
        self._dbusservice.add_path("/Ac/L1/Current", None, gettextcallback=text_a)
        self._dbusservice.add_path("/Ac/L1/Voltage", None, gettextcallback=text_v)
        self._dbusservice.add_path("/Ac/L1/Frequency", None, gettextcallback=text_hz)
        self._dbusservice.add_path("/Ac/L1/PowerFactor", None, gettextcallback=text_pf)
        self._dbusservice.add_path("/Ac/L1/Energy/Forward", None, gettextcallback=text_kwh)

        self._dbusservice.register()
        logging.info("Created D-Bus service for OpenDTU inverter %s", serial)

    def update_metric(self, metric, value):
        self.last_seen = int(time())
        self._dbusservice["/Connected"] = 1

        if metric == "power":
            self.power = round(value, 2)
            self._dbusservice["/Ac/Power"] = self.power
            self._dbusservice["/Ac/L1/Power"] = self.power

            status = 7 if self.power >= 10 else 8
            self._dbusservice["/StatusCode"] = status
            self._dbusservice["/Ac/StatusCode"] = status
        elif metric == "current":
            self._dbusservice["/Ac/Current"] = round(value, 2)
            self._dbusservice["/Ac/L1/Current"] = round(value, 2)
        elif metric == "voltage":
            self._dbusservice["/Ac/Voltage"] = round(value, 2)
            self._dbusservice["/Ac/L1/Voltage"] = round(value, 2)
        elif metric == "frequency":
            self._dbusservice["/Ac/L1/Frequency"] = round(value, 2)
        elif metric == "powerfactor":
            self._dbusservice["/Ac/L1/PowerFactor"] = round(value, 3)
        elif metric == "yieldtotal":
            self._dbusservice["/Ac/Energy/Forward"] = round(value, 3)
            self._dbusservice["/Ac/L1/Energy/Forward"] = round(value, 3)

        index = self._dbusservice["/UpdateIndex"] + 1
        self._dbusservice["/UpdateIndex"] = 0 if index > 255 else index

    def update_name(self, name):
        if not name or name == self.name:
            return

        self.name = name
        self._dbusservice["/CustomName"] = name
        self._dbusservice["/Mgmt/Connection"] = "OpenDTU MQTT %s (%s)" % (self.serial, name)

    def close(self):
        logging.info("Removing D-Bus service for inactive OpenDTU inverter %s", self.serial)
        self._dbusservice["/Connected"] = 0
        self._dbusservice.__del__()

    def _handle_max_power_changed(self, path, value):
        try:
            limit = max(0, int(float(value)))
            payload = json.dumps({"value": limit})
            topic = command_topic(self.serial)
            mqtt_client.publish(topic, payload=payload, qos=0, retain=False)
            logging.info("Sent OpenDTU limit for %s: %s W", self.serial, limit)
            return True
        except Exception:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logging.error("Failed to publish OpenDTU limit: %r of type %s in %s line #%s", exception_object, exception_type, file, line)
            return False


class OpenDtuManager:
    def __init__(self):
        self.inverters = {}
        self.device_instances = load_device_instance_map()
        self.used_device_instances = used_device_instances()
        self.names = {}

    def handle_metric_message(self, serial, metric, value):
        service = self.inverters.get(serial)
        if service is None:
            service = OpenDtuInverterService(serial, self._device_instance_for(serial))
            self.inverters[serial] = service
            if serial in self.names:
                service.update_name(self.names[serial])

        service.update_metric(metric, value)
        return False

    def handle_name_message(self, serial, name):
        self.names[serial] = name
        service = self.inverters.get(serial)
        if service is not None:
            service.update_name(name)
        return False

    def cleanup_inactive(self):
        timeout = DEFAULT_INVERTER_TIMEOUT
        if timeout <= 0:
            return True

        now = int(time())
        inactive = [
            serial
            for serial, service in self.inverters.items()
            if now - service.last_seen > timeout
        ]
        for serial in inactive:
            self.inverters.pop(serial).close()

        return True

    def _device_instance_for(self, serial):
        if serial in self.device_instances:
            deviceinstance = self.device_instances[serial]
            if deviceinstance not in self.used_device_instances:
                self.used_device_instances.add(deviceinstance)
                return deviceinstance
            logging.warning("Stored DeviceInstance %s for %s is already used. Assigning a new one.", deviceinstance, serial)

        deviceinstance = FIRST_DEVICE_INSTANCE
        used = self.used_device_instances.union(set(self.device_instances.values()))
        while deviceinstance in used:
            deviceinstance += 1

        self.device_instances[serial] = deviceinstance
        self.used_device_instances.add(deviceinstance)
        save_device_instance_map(self.device_instances)
        return deviceinstance


def parse_opendtu_topic(topic):
    parts = topic.split("/")
    base_parts = base_topic().split("/")
    if parts[: len(base_parts)] != base_parts:
        return None

    remaining = parts[len(base_parts) :]
    if len(remaining) < 2:
        return None

    serial = remaining[0]
    if not INVERTER_SERIAL_RE.match(serial):
        return None

    if len(remaining) == 2 and remaining[1] == "name":
        return serial, "name"

    if len(remaining) == 3 and remaining[1] == "0":
        return serial, remaining[2]

    return None


def on_disconnect(client, userdata, flags, reason_code, properties):
    logging.warning("MQTT client: disconnected with reason code %s", reason_code)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        topic = opendtu_topic()
        logging.info("MQTT client: connected, subscribing to %s", topic)
        client.subscribe(topic)
    else:
        logging.error("MQTT client: failed to connect, return code %s", reason_code)


def on_message(client, userdata, msg):
    try:
        parsed_topic = parse_opendtu_topic(msg.topic)
        if parsed_topic is None:
            logging.debug("Ignoring MQTT topic outside OpenDTU inverter data: %s", msg.topic)
            return

        serial, metric = parsed_topic
        if metric == "name":
            GLib.idle_add(manager.handle_name_message, serial, parse_text_payload(msg.payload))
        elif metric in ("power", "current", "voltage", "frequency", "powerfactor", "yieldtotal"):
            GLib.idle_add(manager.handle_metric_message, serial, metric, parse_float_payload(msg.payload))
    except Exception:
        exception_type, exception_object, exception_traceback = sys.exc_info()
        file = exception_traceback.tb_frame.f_code.co_filename
        line = exception_traceback.tb_lineno
        logging.error("Failed to process MQTT message: %r of type %s in %s line #%s", exception_object, exception_type, file, line)
        logging.debug("MQTT topic: %s payload: %s", msg.topic, msg.payload)


def setup_mqtt_client():
    client_id = "OpenDtuPv_%s" % get_vrm_portal_id()
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    client.on_disconnect = on_disconnect
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=5, max_delay=60)

    username = config["MQTT"].get("username", "")
    password = config["MQTT"].get("password", "")
    if username and password:
        logging.info('MQTT client: using username "%s"', username)
        client.username_pw_set(username=username, password=password)

    return client


def main():
    global config, manager, mqtt_client

    from dbus.mainloop.glib import DBusGMainLoop  # pyright: ignore[reportMissingImports]

    DBusGMainLoop(set_as_default=True)

    config = load_config()
    setup_logging()
    manager = OpenDtuManager()

    mqtt_client = setup_mqtt_client()
    logging.info(
        "MQTT client: connecting to broker %s on port %s",
        config["MQTT"]["broker_address"],
        config["MQTT"].get("broker_port", "1883"),
    )
    mqtt_client.connect(
        host=config["MQTT"]["broker_address"],
        port=int(config["MQTT"].get("broker_port", "1883")),
    )
    mqtt_client.loop_start()

    GLib.timeout_add_seconds(10, manager.cleanup_inactive)

    logging.info("Connected to D-Bus and switching over to GLib.MainLoop()")
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
