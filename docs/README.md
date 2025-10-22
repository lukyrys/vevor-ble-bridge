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

- `BLE_MAC_ADDRESS` - MAC address of your Vevor heater
- `BLE_PASSKEY` - Heater passkey (default: 1234)
- `MQTT_HOST` - MQTT broker address
- `MQTT_USERNAME` / `MQTT_PASSWORD` - MQTT credentials
- `DEVICE_NAME` - Friendly name for Home Assistant

## Recent Improvements

### Error Handling & Reliability

- Automatic BLE reconnection on connection loss
- MQTT publish acknowledgment with 5-second timeout
- Comprehensive error logging and recovery
- CCCD (Client Characteristic Configuration Descriptor) enabled for reliable notifications

### BLE Communication

- Polling loop for notifications (100ms intervals, 1s timeout)
- Improved checksum calculation
- Better error differentiation (disconnection vs timeout vs general errors)

### MQTT Integration

- `on_disconnect` callback for broker connection monitoring
- `on_publish` callback for message delivery tracking
- Try-catch blocks around MQTT operations
- Offline status reporting during reconnection attempts

## Credits

This project is based on the original work by [Bartosz Derleta](https://github.com/bderleta/vevor-ble-bridge), with improvements from:

- [n13ldo/dh-ble-bridge](https://github.com/n13ldo/dh-ble-bridge) - MQTT error handling improvements
- [Knutnoh/vevor-ble-bridge](https://github.com/Knutnoh/vevor-ble-bridge) - BLE notification improvements

## License

This project is licensed under the GPL-3.0 License - see the [LICENSE](../LICENSE) file for details.
