# Vevor BLE Bridge Documentation

This documentation provides comprehensive information about the Vevor BLE Bridge project, a Bluetooth Low Energy to MQTT bridge for Vevor diesel heaters.

## Table of Contents

1. [Architecture Overview](ARCHITECTURE.md)
2. [BLE Protocol Documentation](BLE_PROTOCOL.md)
3. [MQTT Integration & Home Assistant](MQTT_INTEGRATION.md)
4. [Troubleshooting Guide](TROUBLESHOOTING.md)
5. [Changelog](CHANGELOG.md)

## Quick Start

The Vevor BLE Bridge connects to a Vevor diesel heater via Bluetooth Low Energy and exposes its functionality through MQTT, making it compatible with Home Assistant and other home automation systems.

### Key Features

- Automatic BLE reconnection with exponential backoff
- MQTT autodiscovery for Home Assistant
- Error recovery and logging
- Docker containerization
- Support for both power level and temperature control modes

### Basic Setup

1. Configure environment variables in `.env` file
2. Build and run with Docker Compose:
   ```bash
   docker-compose up -d
   ```

3. The bridge will automatically:
   - Connect to your Vevor heater via BLE
   - Register with Home Assistant via MQTT discovery
   - Begin polling heater status every 2 seconds

### Environment Variables

See `.env.sample` for a complete list of required environment variables:

**Required:**
- `BLE_MAC_ADDRESS` - MAC address of your Vevor heater
- `MQTT_HOST` - MQTT broker address
- `DEVICE_NAME` - Friendly name for Home Assistant

**Optional:**
- `BLE_PASSKEY` - Heater passkey (default: 1234)
- `MQTT_USERNAME` / `MQTT_PASSWORD` - MQTT credentials
- `OVERHEAT_THRESHOLD` - Critical temperature in °C (default: 256)
- `TEMP_LEVEL_LIMITING` - Enable progressive level limiting (default: true)

## Recent Improvements

### Watchdog & Recovery

- **Consecutive failure detection** - Reconnects after 3 failed polls
- **Watchdog timeout** - Forces reconnect if no response for 30 seconds
- **Prevents stuck states** - Especially during rapid command sequences
- **System state tracking** - Publishes detailed connection state to MQTT

### Overheat Protection

- **Progressive level limiting** - Automatically limits maximum power level based on temperature (configurable)
  - < 235°C: No limitation (full power available)
  - 235-240°C: Max level 10
  - 240-245°C: Max level 8
  - 245-250°C: Max level 6
  - 250-253°C: Max level 4
  - 253-256°C: Max level 2
  - >= 256°C: Force level 1 (critical overheat)
- **Automatic safety shutoff** - Reduces power to level 1 at critical temperature (default 256°C, configurable)
- **60-second lockout** - Blocks level/temp/mode commands during overheat cooldown
- **Extended lockout** - If temperature continues rising at level 1, extends lockout to 5 minutes
- **Persistent state** - Maintains overheat status for full lockout period regardless of temperature
- **Emergency override** - Start/stop commands still work during lockout
- **No auto-restore** - Level remains at 1 after lockout, requires manual increase (prevents repeat overheat)

### Error Handling & Reliability

- Automatic BLE reconnection on connection loss with exponential backoff
- MQTT publish acknowledgment with 5-second timeout
- Comprehensive error logging and recovery
- System state published to MQTT (Connected, Disconnected, Reconnecting, Overheat Active, etc.)

### BLE Communication

- Polling loop for notifications (100ms intervals, 1s timeout)
- Improved checksum calculation
- Better error differentiation (disconnection vs timeout vs general errors)
- Connection retry with configurable timeout and delay

### MQTT Integration

- `on_disconnect` callback for broker connection monitoring
- `on_publish` callback for message delivery tracking (disabled by default - too noisy)
- Try-catch blocks around MQTT operations
- Detailed status reporting with system state annotations
- Offline status reporting during reconnection attempts

## Credits

This project is based on the original work by [Bartosz Derleta](https://github.com/bderleta/vevor-ble-bridge), with improvements from:

- [n13ldo/dh-ble-bridge](https://github.com/n13ldo/dh-ble-bridge) - MQTT error handling improvements
- [Knutnoh/vevor-ble-bridge](https://github.com/Knutnoh/vevor-ble-bridge) - BLE notification improvements

## License

This project is licensed under the GPL-3.0 License - see the [LICENSE](../LICENSE) file for details.
