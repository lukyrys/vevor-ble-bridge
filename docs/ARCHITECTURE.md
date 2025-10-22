# Architecture Overview

## System Components

The Vevor BLE Bridge consists of three main components:

```
┌─────────────────┐     BLE      ┌──────────────┐     MQTT     ┌───────────────┐
│  Vevor Heater   │◄────────────►│  BLE Bridge  │◄────────────►│ Home Assistant│
└─────────────────┘              └──────────────┘              └───────────────┘
                                        │
                                        │ Docker
                                        ▼
                                  ┌──────────────┐
                                  │  Raspberry Pi│
                                  └──────────────┘
```

### 1. BLE Communication Layer (`vevor.py`)

Handles low-level Bluetooth communication with the Vevor heater.

**Key Classes:**

- `DieselHeater` - Main BLE client
  - Connection management with retry logic
  - CCCD activation for notifications
  - Command sending with polling loop
  - Automatic reconnection

- `_DieselHeaterNotification` - Protocol parser
  - Parses binary heater status messages
  - Supports multiple protocol versions (85, 102, 136)
  - Error code translation

- `_DieselHeaterDelegate` - BLE callback handler
  - Receives notifications from heater
  - Passes parsed data to main class

**Connection Flow:**

```python
# Initialize connection
heater = DieselHeater(mac_address, passkey)
  │
  ├─► Connect to BLE peripheral (with retries)
  ├─► Discover services & characteristics
  ├─► Set notification delegate
  └─► Enable CCCD for notifications

# Send command
result = heater.get_status()
  │
  ├─► Build command bytearray
  ├─► Write to characteristic
  ├─► Poll for notification (1s timeout, 100ms intervals)
  └─► Return parsed result
```

### 2. MQTT Integration Layer (`main.py`)

Bridges BLE data to MQTT with Home Assistant discovery support.

**Key Functions:**

- `init_client()` - MQTT client setup with callbacks
- `publish_ha_config()` - Home Assistant autodiscovery
- `dispatch_result()` - Publish heater status to MQTT
- `on_message()` - Handle incoming MQTT commands
- `on_disconnect()` - Monitor broker connection
- `on_publish()` - Track message delivery

**Main Loop:**

```python
while run:
    try:
        if vdh is None:
            vdh = vevor.DieselHeater(...)

        result = vdh.get_status()
        dispatch_result(result)
        time.sleep(poll_interval)

    except BTLEDisconnectError:
        # Reconnect with backoff
    except TimeoutError:
        # Handle timeout
    except Exception:
        # Log and recover
```

### 3. Docker Container

Provides isolated environment with required dependencies.

**Container Configuration:**

- Network mode: `host` (for BLE access)
- Capabilities: `NET_ADMIN`, `NET_RAW` (for BLE)
- Auto-restart: `always`
- Optional: Periodic restart service

## Data Flow

### Status Updates (BLE → MQTT)

```
1. Poll heater every 2 seconds
   └─► vdh.get_status()

2. Parse BLE notification
   └─► _DieselHeaterNotification(data)

3. Extract status fields:
   - running_state, running_step
   - error codes
   - temperatures (room, case)
   - voltage, altitude
   - current level/temperature setting

4. Publish to MQTT topics:
   - status/state
   - room_temperature/state
   - heater_temperature/state
   - voltage/state
   - altitude/state
   - level/state or temperature/state

5. Update availability topics
```

### Commands (MQTT → BLE)

```
1. Receive MQTT message
   └─► on_message(topic, payload)

2. Parse command type:
   - start/cmd → vdh.start()
   - stop/cmd → vdh.stop()
   - level/cmd → vdh.set_level(value)
   - temperature/cmd → vdh.set_level(value)
   - mode/cmd → vdh.set_mode(mode)

3. Send BLE command
   └─► _send_command(cmd, arg)

4. Wait for notification (acknowledgment)

5. Publish updated status
   └─► dispatch_result(result)
```

## Error Handling Strategy

### BLE Errors

**Connection Loss:**
```
BTLEDisconnectError
  │
  ├─► Set vdh = None
  ├─► Publish "Disconnected" status to MQTT
  ├─► Wait with exponential backoff
  └─► Retry connection (max 5 attempts)
```

**Timeout:**
```
No notification received within 1s
  │
  ├─► Return None
  ├─► Main loop catches and handles
  └─► Attempt reconnection
```

### MQTT Errors

**Publish Failure:**
```
client.publish() with try-catch
  │
  ├─► Wait for ACK (5s timeout)
  ├─► Log success/failure
  └─► on_publish() callback tracks delivery
```

**Connection Loss:**
```
on_disconnect() callback
  │
  ├─► Log disconnect reason (rc)
  └─► MQTT client auto-reconnects
```

## Configuration Management

### Environment Variables

All configuration is loaded from environment variables:

```python
# BLE Configuration
ble_mac_address = os.environ["BLE_MAC_ADDRESS"]
ble_passkey = int(os.environ.get("BLE_PASSKEY", 1234))
ble_poll_interval = int(os.environ.get("BLE_POLL_INTERVAL", 2))

# MQTT Configuration
mqtt_host = os.environ.get("MQTT_HOST", "127.0.0.1")
mqtt_username = os.environ.get("MQTT_USERNAME")
mqtt_password = os.environ.get("MQTT_PASSWORD")
mqtt_port = int(os.environ.get("MQTT_PORT", 1883))
mqtt_prefix = os.environ.get("MQTT_PREFIX", "")

# Device Configuration
device_name = os.environ["DEVICE_NAME"]
device_manufacturer = os.environ.get("DEVICE_MANUFACTURER", "Vevor")
device_model = os.environ["DEVICE_MODEL"]
```

### Docker Compose

Environment variables are injected via `.env` file:

```yaml
environment:
  BLE_MAC_ADDRESS: ${BLE_MAC_ADDRESS}
  BLE_PASSKEY: ${BLE_PASSKEY}
  # ...
```

## Performance Characteristics

### Polling Interval

- Default: 2 seconds
- Configurable via `BLE_POLL_INTERVAL`
- Minimum recommended: 1 second
- Maximum recommended: 10 seconds

### BLE Timeouts

- Connection timeout: 10 seconds (with retries)
- Notification wait: 1 second (polling every 100ms)
- Reconnection delay: 5 seconds (exponential backoff)

### MQTT Timeouts

- Publish acknowledgment: 5 seconds
- Connection auto-reconnect enabled
- Clean session: True (no message persistence)

## Security Considerations

### BLE Security

- Passkey authentication (default: 1234)
- No encryption beyond BLE pairing
- MAC address filtering via configuration

### MQTT Security

- Username/password authentication
- TLS/SSL not configured by default
- Recommend: Use VPN or local network only

### Docker Security

- Runs as root (required for BLE access)
- Host network mode (required for BLE)
- No exposed ports
- Limited capabilities: NET_ADMIN, NET_RAW only

## Deployment Options

### Standard Deployment

```bash
docker-compose up -d
```

### Development Mode

```bash
# Build and run with logs
docker-compose up --build

# View logs
docker logs -f vevor_bridge
```

### Production Recommendations

1. Enable MQTT TLS/SSL
2. Use strong MQTT credentials
3. Configure firewall rules
4. Monitor container health
5. Set up log rotation
6. Enable the auto-restart service
