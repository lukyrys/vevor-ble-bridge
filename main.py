# Vevor BLE Bridge
# 2024 Bartosz Derleta <bartosz@derleta.com>

import paho.mqtt.client as mqtt
import logging
import platform
import json
import time
import vevor
import os
import sys
import subprocess
import gc
import threading
from bluepy.btle import BTLEDisconnectError, BTLEInternalError

# = Configuration
# == BLE bridge
ble_mac_address = os.environ["BLE_MAC_ADDRESS"]
ble_passkey = int(os.environ["BLE_PASSKEY"]) if os.environ.get("BLE_PASSKEY") else 1234
ble_poll_interval = (
    int(os.environ["BLE_POLL_INTERVAL"]) if os.environ.get("BLE_POLL_INTERVAL") else 2
)
# == Device
device_name = os.environ["DEVICE_NAME"]
device_manufacturer = (
    os.environ["DEVICE_MANUFACTURER"]
    if os.environ.get("DEVICE_MANUFACTURER")
    else "Vevor"
)
device_model = os.environ["DEVICE_MODEL"]
device_id = "BYD-" + ble_mac_address.replace(":", "").upper()  # auto
via_device = platform.uname()[1]  # auto
# == MQTT
mqtt_host = os.environ["MQTT_HOST"] if os.environ.get("MQTT_HOST") else "127.0.0.1"
mqtt_username = os.environ.get("MQTT_USERNAME")
mqtt_password = os.environ.get("MQTT_PASSWORD")
mqtt_port = int(os.environ["MQTT_PORT"]) if os.environ.get("MQTT_PORT") else 1883
mqtt_discovery_prefix = (
    os.environ["MQTT_DISCOVERY_PREFIX"]
    if os.environ.get("MQTT_DISCOVERY_PREFIX")
    else "homeassistant"
)
mqtt_prefix = f"{os.environ.get('MQTT_PREFIX', '').rstrip('/')}/{device_id}"

client = None
logger = None
vdh = None
run = True
modes = ["Power Level", "Temperature"]

# Thread lock for BLE operations - bluepy is NOT thread-safe
ble_lock = threading.Lock()

def init_logger():
    logger = logging.getLogger("vevor-ble-bridge")
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S %z"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


def init_client():
    client = mqtt.Client(client_id=device_id, clean_session=True)
    if mqtt_username and len(mqtt_username) and mqtt_password and len(mqtt_password):
        logger.info(
            f"Connecting to MQTT broker {mqtt_username}@{mqtt_host}:{mqtt_port}"
        )
        client.username_pw_set(mqtt_username, mqtt_password)
    else:
        logger.info(f"Connecting to MQTT broker {mqtt_host}:{mqtt_port}")
    # Set all callbacks before connecting
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.on_publish = on_publish
    client.connect(mqtt_host, port=mqtt_port)
    return client


def cleanup_ble_device(device):
    """Properly cleanup BLE device object before reconnect"""
    if device is not None:
        try:
            logger.info("Cleaning up BLE connection...")
            device.disconnect()
            logger.debug("BLE disconnect() called successfully")
        except Exception as e:
            logger.warning(f"Error during BLE disconnect: {e}")

        try:
            # Force garbage collection to cleanup bluepy objects
            del device
            gc.collect()
            logger.debug("BLE object deleted and garbage collected")
        except Exception as e:
            logger.warning(f"Error during BLE cleanup: {e}")

    # Minimal delay to let BLE stack settle - faster reconnect
    time.sleep(0.2)


def reset_ble_adapter():
    """Reset BLE adapter to clear stuck state"""
    try:
        logger.warning("Resetting BLE adapter (hci0)...")
        subprocess.run(["hciconfig", "hci0", "down"], check=False, capture_output=True, timeout=5)
        time.sleep(1)
        subprocess.run(["hciconfig", "hci0", "up"], check=False, capture_output=True, timeout=5)
        time.sleep(2)
        logger.info("BLE adapter reset complete")
        return True
    except subprocess.TimeoutExpired:
        logger.error("BLE adapter reset timed out")
        return False
    except Exception as e:
        logger.error(f"Failed to reset BLE adapter: {e}")
        return False


def get_device_conf():
    conf = {
        "name": device_name,
        "identifiers": device_id,
        "manufacturer": device_manufacturer,
        "model": device_id,
        "via_device": via_device,
        "sw": "Vevor-BLE-Bridge",
    }
    return conf


def publish_ha_config():
    start_conf = {
        "device": get_device_conf(),
        "icon": "mdi:radiator",
        "name": "Start",
        "unique_id": f"{device_id}-000",
        "command_topic": f"{mqtt_prefix}/start/cmd",
        "availability_topic": f"{mqtt_prefix}/start/av",
        "enabled_by_default": True,
    }
    client.publish(
        f"{mqtt_discovery_prefix}/button/{device_id}-000/config",
        json.dumps(start_conf),
        retain=True,
    )

    stop_conf = {
        "device": get_device_conf(),
        "icon": "mdi:radiator-off",
        "name": "Stop",
        "unique_id": f"{device_id}-001",
        "command_topic": f"{mqtt_prefix}/stop/cmd",
        "availability_topic": f"{mqtt_prefix}/stop/av",
        "enabled_by_default": True,
    }
    client.publish(
        f"{mqtt_discovery_prefix}/button/{device_id}-001/config",
        json.dumps(stop_conf),
        retain=True,
    )

    status_conf = {
        "device": get_device_conf(),
        "expire_after": 10,
        "name": "Status",
        "unique_id": f"{device_id}-010",
        "state_topic": f"{mqtt_prefix}/status/state",
    }
    client.publish(
        f"{mqtt_discovery_prefix}/sensor/{device_id}-010/config",
        json.dumps(status_conf),
        retain=True,
    )

    temperature_limiting_conf = {
        "device": get_device_conf(),
        "expire_after": 10,
        "name": "Temperature Limiting",
        "unique_id": f"{device_id}-023",
        "state_topic": f"{mqtt_prefix}/temp_limiting/state",
        "icon": "mdi:thermometer-alert",
    }
    client.publish(
        f"{mqtt_discovery_prefix}/sensor/{device_id}-023/config",
        json.dumps(temperature_limiting_conf),
        retain=True,
    )

    overheat_protection_conf = {
        "device": get_device_conf(),
        "expire_after": 10,
        "name": "Overheat Protection",
        "unique_id": f"{device_id}-024",
        "state_topic": f"{mqtt_prefix}/overheat/state",
        "icon": "mdi:fire-alert",
    }
    client.publish(
        f"{mqtt_discovery_prefix}/sensor/{device_id}-024/config",
        json.dumps(overheat_protection_conf),
        retain=True,
    )

    room_temperature_conf = {
        "device": get_device_conf(),
        "expire_after": 10,
        "name": "Room temperature",
        "device_class": "temperature",
        "unit_of_measurement": "°C",
        "icon": "mdi:home-thermometer",
        "unique_id": f"{device_id}-011",
        "state_topic": f"{mqtt_prefix}/room_temperature/state",
    }
    client.publish(
        f"{mqtt_discovery_prefix}/sensor/{device_id}-011/config",
        json.dumps(room_temperature_conf),
        retain=True,
    )

    heater_temperature_conf = {
        "device": get_device_conf(),
        "expire_after": 10,
        "name": "Heater temperature",
        "device_class": "temperature",
        "unit_of_measurement": "°C",
        "icon": "mdi:thermometer-lines",
        "unique_id": f"{device_id}-012",
        "state_topic": f"{mqtt_prefix}/heater_temperature/state",
    }
    client.publish(
        f"{mqtt_discovery_prefix}/sensor/{device_id}-012/config",
        json.dumps(heater_temperature_conf),
        retain=True,
    )

    voltage_conf = {
        "device": get_device_conf(),
        "expire_after": 10,
        "name": "Supply voltage",
        "device_class": "voltage",
        "unit_of_measurement": "V",
        "icon": "mdi:car-battery",
        "unique_id": f"{device_id}-013",
        "state_topic": f"{mqtt_prefix}/voltage/state",
    }
    client.publish(
        f"{mqtt_discovery_prefix}/sensor/{device_id}-013/config",
        json.dumps(voltage_conf),
        retain=True,
    )

    altitude_conf = {
        "device": get_device_conf(),
        "expire_after": 10,
        "name": "Altitude",
        "device_class": "distance",
        "unit_of_measurement": "m",
        "icon": "mdi:summit",
        "unique_id": f"{device_id}-014",
        "state_topic": f"{mqtt_prefix}/altitude/state",
    }
    client.publish(
        f"{mqtt_discovery_prefix}/sensor/{device_id}-014/config",
        json.dumps(altitude_conf),
        retain=True,
    )

    mode_select_conf = {
        "device": get_device_conf(),
        "name": "Mode",
        "availability_topic": f"{mqtt_prefix}/mode/av",
        "command_topic": f"{mqtt_prefix}/mode/cmd",
        "state_topic": f"{mqtt_prefix}/mode/state",
        "enabled_by_default": True,
        "unique_id": f"{device_id}-021",
        "options": modes
    }
    client.publish(
        f"{mqtt_discovery_prefix}/select/{device_id}-021/config",
        json.dumps(mode_select_conf),
        retain=True,
    )

    level_conf = {
        "device": get_device_conf(),
        "name": "Power Level",
        "availability_topic": f"{mqtt_prefix}/level/av",
        "command_topic": f"{mqtt_prefix}/level/cmd",
        "state_topic": f"{mqtt_prefix}/level/state",
        "enabled_by_default": True,
        "icon": "mdi:speedometer",
        "unique_id": f"{device_id}-020",
        "min": 1.0,
        "max": 10.0,
        "step": 1.0,
    }
    client.publish(
        f"{mqtt_discovery_prefix}/number/{device_id}-020/config",
        json.dumps(level_conf),
        retain=True,
    )
    
    temperature_conf = {
        "device": get_device_conf(),
        "name": "Temperature",
        "availability_topic": f"{mqtt_prefix}/temperature/av",
        "command_topic": f"{mqtt_prefix}/temperature/cmd",
        "state_topic": f"{mqtt_prefix}/temperature/state",
        "enabled_by_default": True,
        "icon": "mdi:thermometer",
        "unique_id": f"{device_id}-022",
        "min": 8.0,
        "max": 36.0,
        "step": 1.0,
    }
    client.publish(
        f"{mqtt_discovery_prefix}/number/{device_id}-022/config",
        json.dumps(temperature_conf),
        retain=True,
    )   

def on_connect(client, userdata, flags, rc):
    global run
    if rc:
        run = False
        raise RuntimeError("Cannot connect to MQTT broker (error %d)" % rc)
    logger.info("Connected to MQTT broker")
    client.subscribe(
        [
            (f"{mqtt_prefix}/start/cmd", 2),
            (f"{mqtt_prefix}/stop/cmd", 2),
            (f"{mqtt_prefix}/level/cmd", 2),
            (f"{mqtt_prefix}/temperature/cmd", 2),
            (f"{mqtt_prefix}/mode/cmd", 2),
        ]
    )
    publish_ha_config()
    # Initialize temperature limiting and overheat protection sensors
    client.publish(f"{mqtt_prefix}/temp_limiting/state", "Inactive")
    client.publish(f"{mqtt_prefix}/overheat/state", "Inactive")


def on_disconnect(client, userdata, rc):
    """
    This callback is called when the client disconnects from the broker.
    An rc (result code) different from 0 usually indicates an unexpected disconnect.
    Paho MQTT with loop_start() will auto-reconnect, but we log and assist if needed.
    """
    if rc == 0:
        logger.info("Disconnected from MQTT broker (clean disconnect)")
    else:
        logger.warning(f"Unexpected disconnect from MQTT broker (rc={rc}), auto-reconnect will attempt...")
        # Paho's loop_start() handles reconnection automatically
        # on_connect will be called again when reconnected, which will re-publish HA config


def dispatch_result(result):
    global system_state, mqtt_publish_failures
    stop_pub = False
    start_pub = False
    level_pub = False
    temperature_pub = False
    mode_pub = False
    if result:
        logger.debug(str(result.data()))
        msg = result.running_step_msg
        if result.error:
            msg = f"{msg} ({result.error_msg})"

        # Add system state ONLY for connection issues (not for temperature limiting or overheat)
        if system_state != "Connected" and not system_state.startswith("Temperature limiting") and system_state != "Overheat Active":
            msg = f"{msg} [{system_state}]"

        logger.debug(f"Publishing status: '{msg}' (system_state: '{system_state}')")
        try:
            info = client.publish(f"{mqtt_prefix}/status/state", msg, qos=1)
            r = info.wait_for_publish(5)
            if not r:
                logger.debug("Publish successful (ACK received)")
                mqtt_publish_failures = 0  # Reset failure counter on success
            else:
                # If wait_for_publish() returns True, that indicates a timeout or failure
                mqtt_publish_failures += 1
                logger.warning(f"MQTT publish timeout/failure (count: {mqtt_publish_failures}/{max_mqtt_publish_failures})")

        except Exception as e:
            mqtt_publish_failures += 1
            logger.warning(f"MQTT publish exception: {e} (count: {mqtt_publish_failures}/{max_mqtt_publish_failures})")

        client.publish(f"{mqtt_prefix}/room_temperature/state", result.cab_temperature)
        if result.running_mode:
            client.publish(f"{mqtt_prefix}/mode/av", "online")
            client.publish(f"{mqtt_prefix}/mode/state", modes[result.running_mode - 1])
            mode_pub = True
        if result.running_step:
            client.publish(f"{mqtt_prefix}/voltage/state", result.supply_voltage)
            client.publish(f"{mqtt_prefix}/altitude/state", result.altitude)
            client.publish(
                f"{mqtt_prefix}/heater_temperature/state", result.case_temperature
            )
            client.publish(f"{mqtt_prefix}/level/state", result.set_level)
            if result.set_temperature is not None:
                client.publish(f"{mqtt_prefix}/temperature/state", result.set_temperature)
            if ((result.running_mode == 0) or (result.running_mode == 1)) and (result.running_step < 4):
                client.publish(f"{mqtt_prefix}/level/av", "online")
                level_pub = True
            if result.running_mode == 2:
                client.publish(f"{mqtt_prefix}/temperature/av", "online")
                temperature_pub = True
            if (result.running_step > 0) and (result.running_step < 4):
                client.publish(f"{mqtt_prefix}/stop/av", "online")
                stop_pub = True
        else:
            client.publish(f"{mqtt_prefix}/start/av", "online")
            start_pub = True
    if not stop_pub:
        client.publish(f"{mqtt_prefix}/stop/av", "offline")
    if not start_pub:
        client.publish(f"{mqtt_prefix}/start/av", "offline")
    if not level_pub:
        client.publish(f"{mqtt_prefix}/level/av", "offline")
    if not temperature_pub:
        client.publish(f"{mqtt_prefix}/temperature/av", "offline")
    if not mode_pub:
        client.publish(f"{mqtt_prefix}/mode/av", "offline")


# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    global overheat_active, overheat_start_time, vdh, current_case_temperature

    # Check if device is connected
    if vdh is None:
        logger.warning(f"Command received while device disconnected: {msg.topic}")
        client.publish(f"{mqtt_prefix}/status/state", "Disconnected - command ignored")
        return

    # Check if overheat protection is active and blocking commands
    if overheat_active:
        time_remaining = overheat_lockout_time - (time.time() - overheat_start_time)
        if time_remaining > 0:
            # Block level/temperature/mode changes during overheat lockout
            if msg.topic in [f"{mqtt_prefix}/level/cmd", f"{mqtt_prefix}/temperature/cmd", f"{mqtt_prefix}/mode/cmd"]:
                logger.warning(f"Command blocked due to overheat protection (lockout: {time_remaining:.0f}s remaining)")
                # Publish lockout status to overheat sensor, not main status
                client.publish(f"{mqtt_prefix}/overheat/state", f"LOCKOUT: {time_remaining:.0f}s remaining")
                return

    # Wrap all BLE operations in try/except to prevent MQTT thread crash
    # Use lock to serialize BLE access (bluepy is NOT thread-safe)
    acquired = ble_lock.acquire(timeout=5)
    if not acquired:
        logger.warning(f"Could not acquire BLE lock for command: {msg.topic} (timeout)")
        client.publish(f"{mqtt_prefix}/status/state", "Command skipped: BLE busy")
        return

    try:
        if msg.topic == f"{mqtt_prefix}/start/cmd":
            logger.info("Received START command")
            dispatch_result(vdh.start())
        elif msg.topic == f"{mqtt_prefix}/stop/cmd":
            logger.info("Received STOP command")
            dispatch_result(vdh.stop())
        elif msg.topic == f"{mqtt_prefix}/level/cmd":
            global last_level_limit_warning, current_heater_level
            requested_level = int(msg.payload)
            max_allowed = get_max_allowed_level(current_case_temperature)

            if requested_level > max_allowed:
                # Reduce to max allowed instead of ignoring completely
                if time.time() - last_level_limit_warning > 30:
                    logger.warning(f"Level {requested_level} reduced to {max_allowed} due to temperature limit (temp: {current_case_temperature}°C)")
                    last_level_limit_warning = time.time()
                requested_level = max_allowed

            # Only send command if level actually changed - prevents MQTT spam
            if requested_level == current_heater_level:
                logger.debug(f"Level {requested_level} already set, skipping redundant command")
                return

            logger.info(f"Received LEVEL={requested_level} command (temp: {current_case_temperature}°C)")
            dispatch_result(vdh.set_level(requested_level))
        elif msg.topic == f"{mqtt_prefix}/temperature/cmd":
            logger.info(f"Received TEMPERATURE={int(msg.payload)} command")
            dispatch_result(vdh.set_level(int(msg.payload)))
        elif msg.topic == f"{mqtt_prefix}/mode/cmd":
            logger.info(f"Received MODE={msg.payload} command")
            dispatch_result(vdh.set_mode(modes.index(msg.payload.decode('ascii')) + 1))
        logger.debug(f"{msg.topic} {str(msg.payload)}")
    except Exception as e:
        # Critical: catch all BLE errors to prevent MQTT thread crash
        logger.error(f"BLE command failed in on_message: {e}")
        logger.error(f"Command was: {msg.topic} = {msg.payload}")
        client.publish(f"{mqtt_prefix}/status/state", f"Command failed: {type(e).__name__}")
        # Mark vdh as None to force reconnection in main loop
        # This is safe because main loop will detect vdh=None and reconnect
        global vdh
        vdh = None
        logger.warning("BLE device marked for reconnection due to command failure")
    finally:
        ble_lock.release()


def on_publish(client, userdata, mid):
    """
    This callback is called when a publish message has completed delivery to the broker.
    You can track message IDs (mid) here if you need to confirm each publish.
    """
    # logger.debug(f"on_publish() mid = {mid}")  # Too much noise, uncomment if needed
    pass


logger = init_logger()
client = init_client()
vdh = None
client.loop_start()

# Connection retry settings
max_reconnect_attempts = 5
reconnect_delay = 2  # seconds - faster reconnect attempts
reconnect_attempt = 0
failed_reconnects_total = 0  # Track total failed reconnects for BLE reset
ble_reset_threshold = 5  # Reset BLE adapter after this many failed reconnects (faster reset)

# Watchdog settings
last_successful_poll = time.time()
watchdog_timeout = 10  # seconds - faster detection of connection loss (was 30s)
consecutive_failures = 0
max_consecutive_failures = 2  # reconnect after 2 consecutive failures (faster reaction)

# MQTT health check
last_mqtt_health_check = time.time()
mqtt_health_check_interval = 60  # seconds - check MQTT health every minute
mqtt_publish_failures = 0
max_mqtt_publish_failures = 3  # reconnect MQTT after 3 failed publishes

# Overheat protection settings
overheat_threshold = int(os.environ.get("OVERHEAT_THRESHOLD", 256))  # °C - critical temperature
overheat_lockout_time = 60  # seconds - initial lockout period
overheat_extended_lockout = 300  # seconds - extended lockout if temp still rising
overheat_active = False
overheat_start_time = 0
overheat_last_temp = 0  # Track temperature trend
overheat_temp_rising_count = 0  # Count how many times temp rose during lockout

# Temperature-based level limiting
temp_limiting_enabled = os.environ.get("TEMP_LEVEL_LIMITING", "true").lower() in ["true", "1", "yes"]
current_case_temperature = 0  # Track current temperature for level limiting
current_heater_level = 0  # Track current heater level to prevent redundant commands
last_level_limit_warning = 0  # Timestamp of last level limit warning (to avoid spam)
last_max_allowed_level = 36  # Track max allowed level to detect changes

def get_max_allowed_level(temperature):
    """
    Calculate maximum allowed level based on current temperature.
    Progressive limitation to prevent overheat.
    Can be disabled via TEMP_LEVEL_LIMITING=false
    """
    if not temp_limiting_enabled:
        return 36  # Limiting disabled - no restriction

    if temperature >= overheat_threshold:
        return 1  # Critical - force minimum
    elif temperature >= overheat_threshold - 1:  # 255°C (default)
        return 2  # Very high - severely limited
    elif temperature >= overheat_threshold - 3:  # 253°C (default)
        return 4  # High - significantly limited
    elif temperature >= overheat_threshold - 5:  # 251°C (default)
        return 6  # Elevated - moderately limited
    elif temperature >= overheat_threshold - 8:  # 248°C (default)
        return 8  # Warm - slightly limited
    elif temperature >= overheat_threshold - 11:  # 245°C (default)
        return 10  # Getting warm - minor limitation
    else:
        return 36  # Safe - no limitation

# System state tracking
system_state = "Connected"  # Connected, Reconnecting, Disconnected, Overheat Active, etc.

while run:
    try:
        # Initialize or reconnect if needed
        if vdh is None:
            system_state = "Reconnecting"
            elapsed_since_disconnect = time.time() - last_successful_poll if last_successful_poll > 0 else 0
            logger.info(f"Connecting to BLE device {ble_mac_address}... (offline for {elapsed_since_disconnect:.1f}s)")
            logger.debug(f"Reconnect context: attempt={reconnect_attempt}, total_failures={failed_reconnects_total}, overheat_active={overheat_active}")

            # Reset BLE adapter if too many failures
            if failed_reconnects_total > 0 and failed_reconnects_total % ble_reset_threshold == 0:
                logger.error(f"BLE adapter reset triggered after {failed_reconnects_total} failed reconnects")
                reset_ble_adapter()

            try:
                # Use 5s timeout for faster failure detection
                vdh = vevor.DieselHeater(ble_mac_address, ble_passkey, timeout_sec=5)
                logger.info(f"Successfully connected to BLE device after {elapsed_since_disconnect:.1f}s offline")
                system_state = "Connected"
                reconnect_attempt = 0
                failed_reconnects_total = 0  # Reset counter on success
            except Exception as conn_error:
                logger.error(f"Failed to connect to BLE device: {conn_error}")
                failed_reconnects_total += 1
                # No need to cleanup here - vdh is already None or failed to create
                vdh = None
                raise  # Re-raise to be caught by outer exception handlers

        # Get status and dispatch (with BLE lock for thread safety)
        with ble_lock:
            result = vdh.get_status()

        # Watchdog: check if we got valid result
        if result is not None:
            last_successful_poll = time.time()
            consecutive_failures = 0

            # Update current temperature and level for tracking
            current_case_temperature = result.case_temperature
            current_heater_level = result.set_level

            # Check if temperature limiting status changed
            current_max_allowed = get_max_allowed_level(current_case_temperature)

            # Update temperature limiting sensor when max allowed level changes
            if current_max_allowed != last_max_allowed_level:
                if current_max_allowed < 36:
                    # Temperature limiting is now active or level changed
                    temp_limit_msg = f"Active: max level {current_max_allowed}"
                    logger.info(f"Temperature limiting active: max level {current_max_allowed} (temp: {current_case_temperature}°C)")
                    client.publish(f"{mqtt_prefix}/temp_limiting/state", temp_limit_msg)
                elif last_max_allowed_level < 36:
                    # Returning to normal from limited state
                    logger.info(f"Temperature limiting deactivated (temp: {current_case_temperature}°C)")
                    client.publish(f"{mqtt_prefix}/temp_limiting/state", "Inactive")
                last_max_allowed_level = current_max_allowed

            # Periodic health check log every 30s
            if int(time.time()) % 30 == 0:
                max_allowed = get_max_allowed_level(current_case_temperature)
                logger.debug(f"Health check OK - temp: {current_case_temperature}°C, level: {result.set_level}, max_allowed: {max_allowed}, step: {result.running_step_msg}")

            # Check for heater's own overheat error (error code 5)
            if result.error == 5:  # Overheating error from heater
                if not overheat_active:
                    logger.error(f"Heater reports OVERHEATING error (code 5), activating protection")
                    logger.warning(f"Heater may stop responding during cooldown (typically 30 minutes)")
                    overheat_active = True
                    overheat_start_time = time.time()
                    overheat_last_temp = result.case_temperature
                    overheat_temp_rising_count = 0
                    client.publish(f"{mqtt_prefix}/overheat/state", f"ACTIVE - Error 5 (Overheating)")
                else:
                    # Heater in error 5 may stop responding - log status periodically
                    elapsed_error = time.time() - overheat_start_time
                    if int(elapsed_error) % 60 == 0:  # Every minute
                        logger.info(f"Heater still in error 5 (Overheating) after {elapsed_error/60:.1f} minutes")

            # Overheat protection check
            if overheat_active:
                current_lockout = overheat_lockout_time

                # Monitor temperature trend during lockout
                if result.case_temperature > overheat_last_temp + 2:  # Temp rising by >2°C
                    overheat_temp_rising_count += 1
                    logger.warning(f"Temperature still rising during lockout: {overheat_last_temp}°C -> {result.case_temperature}°C")

                    # If temp rose 3+ times, extend lockout significantly
                    if overheat_temp_rising_count >= 3:
                        current_lockout = overheat_extended_lockout
                        logger.error(f"Temperature continues rising despite level 1! Extending lockout to {overheat_extended_lockout}s")

                overheat_last_temp = result.case_temperature

                # Check if lockout period has expired
                elapsed = time.time() - overheat_start_time
                if elapsed >= current_lockout:
                    logger.info(f"Overheat lockout period expired after {elapsed:.0f}s, controls re-enabled")
                    logger.info(f"Temperature: {result.case_temperature}°C, Level remains at 1 (manual increase required)")
                    overheat_active = False
                    overheat_temp_rising_count = 0
                    client.publish(f"{mqtt_prefix}/overheat/state", "Inactive")
                    # DO NOT restore level automatically - user must manually increase

            elif result.case_temperature >= overheat_threshold:
                # Activate overheat protection
                logger.error(f"OVERHEAT DETECTED: case_temperature={result.case_temperature}°C >= {overheat_threshold}°C")
                logger.error("Reducing power to level 1 and locking controls for 60s")
                overheat_active = True
                overheat_start_time = time.time()
                overheat_last_temp = result.case_temperature
                overheat_temp_rising_count = 0
                client.publish(f"{mqtt_prefix}/overheat/state", f"ACTIVE - Temp {result.case_temperature}°C")

                # Immediately reduce power to 1 (with BLE lock for thread safety)
                try:
                    with ble_lock:
                        vdh.set_level(1)
                except Exception as e:
                    logger.error(f"Failed to reduce power during overheat: {e}")

            dispatch_result(result)
        else:
            consecutive_failures += 1
            time_since_last_poll = time.time() - last_successful_poll
            logger.warning(f"No response from device (failure {consecutive_failures}/{max_consecutive_failures}, {time_since_last_poll:.1f}s since last success)")
            logger.debug(f"Debug state: overheat_active={overheat_active}, system_state={system_state}, vdh={vdh is not None}")

            # Check if we exceeded failure threshold
            if consecutive_failures >= max_consecutive_failures:
                logger.error(f"Device not responding after {max_consecutive_failures} attempts, forcing reconnect")
                logger.error(f"Last successful poll was {time_since_last_poll:.1f}s ago")
                raise RuntimeError("Device not responding - forcing reconnect")

        # Watchdog: check if too much time passed since last successful poll
        time_since_last_poll = time.time() - last_successful_poll
        if time_since_last_poll > watchdog_timeout:
            logger.error(f"WATCHDOG TIMEOUT: no successful poll for {time_since_last_poll:.1f}s (limit {watchdog_timeout}s)")
            logger.error(f"Debug: consecutive_failures={consecutive_failures}, overheat_active={overheat_active}")
            logger.error(f"Forcing BLE reconnection...")
            raise RuntimeError("Watchdog timeout - forcing reconnect")

        # MQTT health check: periodically verify MQTT is working (but don't force reconnect unless truly needed)
        if time.time() - last_mqtt_health_check >= mqtt_health_check_interval:
            last_mqtt_health_check = time.time()

            # Only log health check, don't force reconnect
            # The library's auto-reconnect should handle disconnections
            if not client.is_connected():
                logger.warning("MQTT health check: client reports disconnected (waiting for auto-reconnect)")
            elif mqtt_publish_failures >= max_mqtt_publish_failures:
                logger.error(f"MQTT health check WARNING: {mqtt_publish_failures} consecutive publish failures")
            else:
                logger.debug(f"MQTT health check OK: connected={client.is_connected()}, failures={mqtt_publish_failures}")

        time.sleep(ble_poll_interval)

    except BTLEDisconnectError as e:
        logger.error(f"BLE disconnected: {e}")
        logger.error(f"Context: consecutive_failures={consecutive_failures}, time_since_last_poll={time.time() - last_successful_poll:.1f}s")
        logger.error(f"Overheat: active={overheat_active}, last_temp={overheat_last_temp}°C")
        cleanup_ble_device(vdh)
        vdh = None
        system_state = "Disconnected"
        # Publish offline status to MQTT
        client.publish(f"{mqtt_prefix}/status/state", system_state)
        reconnect_attempt += 1

        if reconnect_attempt >= max_reconnect_attempts:
            logger.error(f"Failed to reconnect after {max_reconnect_attempts} attempts")
            logger.error(f"Resetting reconnect counter and waiting {reconnect_delay * 3}s before retry")
            system_state = "Connection Failed"
            client.publish(f"{mqtt_prefix}/status/state", system_state)
            reconnect_attempt = 0
            time.sleep(reconnect_delay * 3)  # Wait longer before trying again
        else:
            logger.info(f"Attempting to reconnect in {reconnect_delay}s (attempt {reconnect_attempt}/{max_reconnect_attempts})...")
            system_state = "Reconnecting"
            time.sleep(reconnect_delay)

    except TimeoutError as e:
        logger.error(f"BLE timeout: {e}")
        logger.error(f"Context: consecutive_failures={consecutive_failures}, time_since_last_poll={time.time() - last_successful_poll:.1f}s")
        cleanup_ble_device(vdh)
        vdh = None
        system_state = "Timeout"
        client.publish(f"{mqtt_prefix}/status/state", system_state)
        logger.info(f"Waiting {reconnect_delay}s before reconnect...")
        time.sleep(reconnect_delay)

    except RuntimeError as e:
        # Watchdog or other runtime errors
        logger.error(f"Runtime error: {e}")
        logger.error(f"Context: consecutive_failures={consecutive_failures}, time_since_last_poll={time.time() - last_successful_poll:.1f}s")
        logger.error(f"Overheat: active={overheat_active}, system_state={system_state}")
        cleanup_ble_device(vdh)
        vdh = None
        system_state = "Watchdog Triggered"
        client.publish(f"{mqtt_prefix}/status/state", system_state)
        consecutive_failures = 0
        logger.info(f"Waiting {reconnect_delay}s before reconnect...")
        time.sleep(reconnect_delay)

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(f"Context: consecutive_failures={consecutive_failures}, time_since_last_poll={time.time() - last_successful_poll:.1f}s")
        logger.exception("Full traceback:")
        cleanup_ble_device(vdh)
        vdh = None
        system_state = "Error"
        client.publish(f"{mqtt_prefix}/status/state", system_state)
        consecutive_failures = 0
        logger.info(f"Waiting {reconnect_delay}s before reconnect...")
        time.sleep(reconnect_delay)
