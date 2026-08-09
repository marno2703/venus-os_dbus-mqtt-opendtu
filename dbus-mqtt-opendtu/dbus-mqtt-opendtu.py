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
DEFAULT_MINIMUM_LIMIT_WATTS = 5
FIRST_DEVICE_INSTANCE = 100
INVERTER_SERIAL_RE = re.compile(r"^\d{8,}$")
MAX_RECORDED_TOPICS = 50

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
    logging.basicConfig(level=logging.DEBUG if debug_enabled() else logging.INFO)
    logging.info("OpenDTU driver debug logging is %s", "enabled" if debug_enabled() else "disabled")


def debug_enabled():
    return config.getboolean("DRIVER", "debug", fallback=False)


def base_topic():
    return config["MQTT"].get("base_topic", DEFAULT_BASE_TOPIC).strip("/")


def opendtu_topic():
    return "%s/#" % base_topic()


def command_topic(serial):
    return "%s/%s/cmd/limit_nonpersistent_absolute" % (base_topic(), serial)


def relative_command_topic(serial):
    return "%s/%s/cmd/limit_nonpersistent_relative" % (base_topic(), serial)


def minimum_limit_watts():
    value = config.getint("DRIVER", "minimum_limit_watts", fallback=DEFAULT_MINIMUM_LIMIT_WATTS)
    return max(0, value)


def sanitize_service_suffix(value):
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", value)
    suffix = suffix.strip("_")
    return suffix or "unknown"


def service_name_for_serial(serial):
    return "com.victronenergy.pvinverter.fronius_%s" % sanitize_service_suffix(serial)


def is_own_service_name(service_name):
    prefix = "com.victronenergy.pvinverter.fronius_"
    if not service_name.startswith(prefix):
        return False

    return INVERTER_SERIAL_RE.match(service_name[len(prefix) :]) is not None


def device_instance_map_file():
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "device_instances.json")


def max_power_map_file():
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "max_powers.json")


def runtime_state_file():
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "runtime_state.json")


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


def load_max_power_map():
    path = max_power_map_file()
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except Exception as err:
        logging.warning("Could not read max power map %s: %s", path, err)
        return {}

    max_powers = {}
    for serial, value in data.items():
        if not INVERTER_SERIAL_RE.match(serial):
            continue
        try:
            max_power = int(float(value))
        except (TypeError, ValueError):
            logging.warning("Ignoring invalid stored max power for %s: %s", serial, value)
            continue
        if max_power > 0:
            max_powers[serial] = max_power

    return max_powers


def save_max_power_map(max_powers):
    write_json_file(max_power_map_file(), max_powers)


def write_json_file(path, data):
    tmp_path = "%s.tmp" % path
    try:
        with open(tmp_path, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.rename(tmp_path, path)
    except Exception as err:
        logging.warning("Could not write %s: %s", path, err)


def json_safe_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    return str(value)


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
            if is_own_service_name(service_name):
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
    return "" if value is None else "%.2fkWh" % float(value)


def text_a(path, value):
    return "" if value is None else "%.1fA" % float(value)


def text_w(path, value):
    return "" if value is None else "%iW" % int(float(value))


def text_v(path, value):
    return "" if value is None else "%.2fV" % float(value)


def text_hz(path, value):
    return "" if value is None else "%.2fHz" % float(value)


def text_pf(path, value):
    return "" if value is None else "%.3f" % float(value)


def text_n(path, value):
    return "" if value is None else "%i" % int(float(value))


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
    def __init__(self, serial, deviceinstance, max_power=None):
        self.serial = serial
        self.last_seen = int(time())
        self.name = None
        self.power = 0.0
        self.max_power = max_power
        self._dbusconn = dbus.SystemBus(private=True)
        self._dbusservice = VeDbusService(
            service_name_for_serial(serial),
            bus=self._dbusconn,
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
        self._dbusservice.add_path("/FroniusDeviceType", 1)

        self._dbusservice.add_path("/Latency", None)
        self._dbusservice.add_path("/ErrorCode", 0)
        self._dbusservice.add_path("/Position", DEFAULT_POSITION)
        self._dbusservice.add_path("/StatusCode", 8)
        self._dbusservice.add_path("/UpdateIndex", 0, gettextcallback=text_n)

        self._dbusservice.add_path("/Ac/Power", 0, gettextcallback=text_w)
        self._dbusservice.add_path("/Ac/Current", None, gettextcallback=text_a)
        self._dbusservice.add_path("/Ac/Voltage", None, gettextcallback=text_v)
        self._dbusservice.add_path("/Ac/Energy/Forward", None, gettextcallback=text_kwh)
        self._dbusservice.add_path("/Ac/MaxPower", self._max_power_value(), gettextcallback=text_w)
        self._dbusservice.add_path(
            "/Ac/PowerLimit",
            self._max_power_value(),
            gettextcallback=text_w,
            writeable=True,
            onchangecallback=self._handle_limit_changed,
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
        logging.info("Created D-Bus service for OpenDTU inverter %s with DeviceInstance %s", serial, deviceinstance)
        if self.max_power is None:
            logging.info("OpenDTU inverter %s max power is unknown; ESS limits will be ignored until learned", serial)
        else:
            logging.info("OpenDTU inverter %s max power is %sW", serial, self.max_power)

    def _max_power_value(self):
        return self.max_power if self.max_power is not None else DEFAULT_MAX_POWER

    def update_metric(self, metric, value):
        self.last_seen = int(time())
        self._dbusservice["/Connected"] = 1
        logging.debug("Updating inverter %s metric %s=%s", self.serial, metric, value)

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
        logging.info("Updated OpenDTU inverter %s name to %s", self.serial, name)

    def set_max_power(self, max_power):
        max_power = int(max_power)
        if max_power <= 0 or max_power == self.max_power:
            return

        self.max_power = max_power
        self._dbusservice["/Ac/MaxPower"] = max_power
        self._dbusservice["/Ac/PowerLimit"] = max_power
        logging.info("Learned OpenDTU inverter %s max power: %sW", self.serial, max_power)

    def _set_power_limit_value(self, value):
        self._dbusservice["/Ac/PowerLimit"] = int(value)
        return False

    def close(self):
        logging.info("Removing D-Bus service for inactive OpenDTU inverter %s", self.serial)
        self._dbusservice["/Connected"] = 0
        self._dbusservice.__del__()
        try:
            self._dbusconn.close()
        except Exception:
            pass

    def _handle_limit_changed(self, path, value):
        logging.info("Received D-Bus limit write for inverter %s: %s=%s", self.serial, path, value)
        try:
            if self.max_power is None:
                logging.warning(
                    "Ignoring ESS limit for inverter %s because max power is not learned yet: %s=%s",
                    self.serial,
                    path,
                    value,
                )
                if manager is not None:
                    manager.record_limit_event(self.serial, path, value, None, None, "max_power_unknown")
                GLib.idle_add(self._set_power_limit_value, self._max_power_value())
                return True

            requested_limit = max(0, int(float(value)))
            limit = min(max(requested_limit, minimum_limit_watts()), self.max_power)
            payload = str(limit)
            topic = command_topic(self.serial)
            result = mqtt_client.publish(topic, payload=payload, qos=0, retain=False)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logging.info(
                    "Published OpenDTU limit for %s to %s: %s (requested %s)",
                    self.serial,
                    topic,
                    payload,
                    requested_limit,
                )
            else:
                logging.error("Failed to queue OpenDTU limit for %s to %s: rc=%s payload=%s", self.serial, topic, result.rc, payload)
            if manager is not None:
                manager.record_limit_event(self.serial, path, value, topic, payload, result.rc)
            GLib.idle_add(self._set_power_limit_value, limit)
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
        self.max_powers = load_max_power_map()
        self.max_power_bootstrap_requested_at = {}
        self.limit_status = {}
        self.limit_status_seen_at = {}
        self.names = {}
        self.pending_metrics = {}
        self.seen_topics = []
        self.ignored_topics = []
        self.limit_events = []

    def handle_metric_message(self, serial, metric, value):
        service = self.inverters.get(serial)
        if service is None:
            self.pending_metrics.setdefault(serial, {})[metric] = value
            logging.debug("Buffered inverter %s metric %s=%s until power is received", serial, metric, value)
            if metric != "power":
                self.write_runtime_state()
                return False

            service = OpenDtuInverterService(serial, self._device_instance_for(serial), self.max_powers.get(serial))
            self.inverters[serial] = service
            if serial in self.names:
                service.update_name(self.names[serial])
            logging.info("Discovered OpenDTU inverter %s from metric %s", serial, metric)

            for pending_metric, pending_value in self.pending_metrics.pop(serial, {}).items():
                if pending_metric != metric:
                    service.update_metric(pending_metric, pending_value)
            self._learn_or_request_max_power(serial)

        service.update_metric(metric, value)
        self.write_runtime_state()
        return False

    def handle_limit_status_message(self, serial, metric, value):
        self.limit_status.setdefault(serial, {})[metric] = value
        self.limit_status_seen_at.setdefault(serial, {})[metric] = time()
        logging.debug("Received OpenDTU inverter %s %s=%s", serial, metric, value)
        self._learn_or_request_max_power(serial)
        self.write_runtime_state()
        return False

    def handle_name_message(self, serial, name):
        self.names[serial] = name
        logging.debug("Received OpenDTU inverter %s name=%s", serial, name)
        service = self.inverters.get(serial)
        if service is not None:
            service.update_name(name)
        self.write_runtime_state()
        return False

    def record_topic(self, topic, parsed_topic):
        target = self.seen_topics if parsed_topic is not None else self.ignored_topics
        target.append({"time": int(time()), "topic": topic})
        del target[:-MAX_RECORDED_TOPICS]
        if parsed_topic is None:
            logging.debug("Ignored MQTT topic: %s", topic)
        else:
            logging.debug("Accepted MQTT topic: %s -> %s", topic, parsed_topic)
        self.write_runtime_state()
        return False

    def record_limit_event(self, serial, path, value, topic, payload, result_code):
        self.limit_events.append(
            {
                "time": int(time()),
                "serial": serial,
                "dbus_path": path,
                "dbus_value": json_safe_value(value),
                "mqtt_topic": topic,
                "mqtt_payload": payload,
                "mqtt_result_code": json_safe_value(result_code),
            }
        )
        del self.limit_events[:-MAX_RECORDED_TOPICS]
        self.write_runtime_state()

    def _learn_or_request_max_power(self, serial):
        service = self.inverters.get(serial)
        if service is None or serial in self.max_powers:
            return

        status = self.limit_status.get(serial, {})
        try:
            relative = float(status.get("limit_relative"))
        except (TypeError, ValueError):
            relative = None

        try:
            absolute = int(round(float(status.get("limit_absolute"))))
        except (TypeError, ValueError):
            absolute = None

        absolute_is_current = True
        if serial in self.max_power_bootstrap_requested_at:
            absolute_is_current = (
                self.limit_status_seen_at.get(serial, {}).get("limit_absolute", 0)
                >= self.max_power_bootstrap_requested_at[serial]
            )

        if relative is not None and relative >= 99.9 and absolute is not None and absolute > 0 and absolute_is_current:
            self.max_powers[serial] = absolute
            save_max_power_map(self.max_powers)
            service.set_max_power(absolute)
            return

        self._request_max_power_bootstrap(serial)

    def _request_max_power_bootstrap(self, serial):
        if serial in self.max_power_bootstrap_requested_at:
            return

        topic = relative_command_topic(serial)
        result = mqtt_client.publish(topic, payload="100", qos=0, retain=False)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            self.max_power_bootstrap_requested_at[serial] = time()
            logging.info("Requested OpenDTU 100%% limit for inverter %s to learn max power", serial)
        else:
            logging.error("Failed to request OpenDTU 100%% limit for inverter %s: rc=%s", serial, result.rc)

    def write_runtime_state(self):
        state = {
            "base_topic": base_topic(),
            "subscription": opendtu_topic(),
            "inverters": {},
            "names": self.names,
            "pending_metrics": self.pending_metrics,
            "limit_events": self.limit_events,
            "seen_topics": self.seen_topics,
            "ignored_topics": self.ignored_topics,
        }

        for serial, service in self.inverters.items():
            state["inverters"][serial] = {
                "service_name": service_name_for_serial(serial),
                "device_instance": json_safe_value(service._dbusservice["/DeviceInstance"]),
                "custom_name": json_safe_value(service._dbusservice["/CustomName"]),
                "connected": json_safe_value(service._dbusservice["/Connected"]),
                "power": json_safe_value(service._dbusservice["/Ac/Power"]),
                "max_power": json_safe_value(service.max_power),
                "limit_status": self.limit_status.get(serial, {}),
                "max_power_bootstrap_requested_at": json_safe_value(self.max_power_bootstrap_requested_at.get(serial)),
                "last_seen": service.last_seen,
            }

        write_json_file(runtime_state_file(), state)

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

    if len(remaining) == 3 and remaining[1] == "status" and remaining[2] in ("limit_relative", "limit_absolute"):
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
        logging.debug("Received MQTT message topic=%s payload=%s", msg.topic, msg.payload)
        parsed_topic = parse_opendtu_topic(msg.topic)
        GLib.idle_add(manager.record_topic, msg.topic, parsed_topic)
        if parsed_topic is None:
            logging.debug("Ignoring MQTT topic outside OpenDTU inverter data: %s", msg.topic)
            return

        serial, metric = parsed_topic
        if metric == "name":
            GLib.idle_add(manager.handle_name_message, serial, parse_text_payload(msg.payload))
        elif metric in ("limit_relative", "limit_absolute"):
            GLib.idle_add(manager.handle_limit_status_message, serial, metric, parse_float_payload(msg.payload))
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
    if debug_enabled():
        client.enable_logger(logging.getLogger("paho.mqtt"))

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
