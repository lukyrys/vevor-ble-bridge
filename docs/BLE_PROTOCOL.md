# BLE Protocol Documentation

This document describes the Bluetooth Low Energy protocol used to communicate with Vevor diesel heaters.

## Overview

The Vevor heater uses a simple command-response protocol over BLE with the following characteristics:

- **Service UUID:** `0000ffe0-0000-1000-8000-00805f9b34fb`
- **Characteristic UUID:** `0000ffe1-0000-1000-8000-00805f9b34fb`
- **Communication:** Write commands to characteristic, receive notifications for responses
- **Authentication:** Passkey (default: 1234)

## Protocol Versions

The heater supports multiple protocol versions identified by the second byte of responses:

| Version | Second Byte | Status |
|---------|-------------|--------|
| v1 | `0x55` (85) | Supported |
| v2 | `0x66` (102) | Supported |
| v3 | `0x88` (136) | Partial support |

## Command Format

Commands are sent as 8-byte arrays:

```
[0xAA] [mode] [auth1] [auth2] [cmd] [arg_low] [arg_high] [checksum]
```

### Byte Breakdown:

| Byte | Purpose | Description |
|------|---------|-------------|
| 0 | Header | Always `0xAA` (170) |
| 1 | Mode | Protocol version: `0x55` or `0x88` |
| 2 | Auth 1 | For `0x55`: `passkey / 100`<br>For `0x88`: random byte |
| 3 | Auth 2 | For `0x55`: `passkey % 100`<br>For `0x88`: random byte |
| 4 | Command | Command code (see table below) |
| 5 | Arg Low | Argument low byte |
| 6 | Arg High | Argument high byte |
| 7 | Checksum | Sum of bytes 0-6, modulo 256 |

### Command Codes:

| Command | Code | Argument | Description |
|---------|------|----------|-------------|
| Get Status | `0x01` | `0x0000` | Request current heater status |
| Set Mode | `0x02` | `0x0001` or `0x0002` | 1=Level mode, 2=Temperature mode |
| Start/Stop | `0x03` | `0x0000` or `0x0001` | 0=Stop, 1=Start |
| Set Level | `0x04` | `0x0001` to `0x0024` | Power level 1-36 |

### Example Command (Get Status):

```python
passkey = 1234
command = bytearray([
    0xAA,              # Header
    0x55,              # Mode (85)
    0x0C,              # 1234 / 100 = 12
    0xD2,              # 1234 % 100 = 210
    0x01,              # Get Status command
    0x00,              # Arg low
    0x00,              # Arg high
    0x00               # Checksum (calculated below)
])
command[7] = sum(command[:7]) % 256  # = 0x84 (132)
```

## Response Format (v1 - 0x55)

Status responses are 20-byte arrays:

```
[0xAA] [0x55] [auth1] [state] [error] [step] [alt_low] [alt_high]
[mode] [setting] [level] [v_low] [v_high] [case_low] [case_high]
[cab_low] [cab_high] [?] [?] [?]
```

### Key Response Fields:

| Bytes | Field | Type | Description |
|-------|-------|------|-------------|
| 0-1 | Header | `0xAA 0x55` | Protocol identifier |
| 3 | Running State | uint8 | 0=Stopped, 1=Running |
| 4 | Error Code | uint8 | See error table below |
| 5 | Running Step | uint8 | 0-4: Standby/Self-test/Ignition/Running/Cooldown |
| 6-7 | Altitude | uint16_le | Altitude in meters |
| 8 | Running Mode | uint8 | 0/1=Level mode, 2=Temperature mode |
| 9 | Setting/Temp | uint8 | Current temperature setting (if mode=2) |
| 10 | Level | uint8 | Current power level (add 1 in mode 0) |
| 11-12 | Supply Voltage | uint16_le | Voltage in 0.1V (divide by 10) |
| 13-14 | Case Temp | int16_le | Chamber temperature in °C |
| 15-16 | Cab Temp | int16_le | Room temperature in °C |

### Error Codes (v1):

| Code | Error Message |
|------|---------------|
| 0 | No fault |
| 1 | Startup failure |
| 2 | Lack of fuel |
| 3 | Supply voltage overrun |
| 4 | Outlet sensor fault |
| 5 | Inlet sensor fault |
| 6 | Pulse pump fault |
| 7 | Fan fault |
| 8 | Ignition unit fault |
| 9 | Overheating |
| 10 | Overheat sensor fault |

### Running Steps:

| Code | Step | Description |
|------|------|-------------|
| 0 | Standby | Heater off or idle |
| 1 | Self-test | Running diagnostics |
| 2 | Ignition | Starting combustion |
| 3 | Running | Stable combustion |
| 4 | Cooldown | Shutdown cooling phase |

## Response Format (v2 - 0x66)

Similar to v1 but with different structure:

```
[0xAA] [0x66] [?] [state] [?] [step] [alt_low] [alt_high]
[mode] [setting] [level] [v_low] [v_high] [case_low] [case_high]
[cab_low] [cab_high] [error] [?] [?]
```

**Key difference:** Error code is at byte 17 instead of byte 4.

### Error Codes (v2):

| Code | Error Message |
|------|---------------|
| 0 | No fault |
| 1 | Supply voltage overrun |
| 3 | Ignition unit fault |
| 4 | Pulse pump fault |
| 5 | Overheating |
| 6 | Fan fault |
| 8 | Lack of fuel |
| 9 | Overheat sensor fault |
| 10 | Startup failure |

## Data Type Conversions

### Signed/Unsigned Conversion:

```python
def _u8tonumber(e):
    """Convert signed int8 to unsigned"""
    return (e + 256) if (e < 0) else e

def _UnsignToSign(e):
    """Convert unsigned int16 to signed"""
    if e > 32767.5:
        e = e | -65536
    return e
```

### Temperature Reading:

```python
# Bytes 13-14: case temperature
case_temp = _UnsignToSign(256 * data[14] + data[13])

# Bytes 15-16: cabin temperature
cab_temp = _UnsignToSign(256 * data[16] + data[15])
```

### Voltage Reading:

```python
# Bytes 11-12: supply voltage
voltage = (256 * data[12] + data[11]) / 10  # in volts
```

## Communication Flow

### Typical Status Poll:

```
1. Write command to characteristic (8 bytes)
   └─► 0xAA 0x55 0x0C 0xD2 0x01 0x00 0x00 0x84

2. Wait for notification (max 1 second)
   └─► Poll every 100ms

3. Receive notification (20 bytes)
   └─► 0xAA 0x55 ... [status data]

4. Parse notification into status object
   └─► {running_state, error, temperatures, etc.}
```

### Error Handling:

**BTLEDisconnectError:**
- Raised when BLE connection is lost
- Requires full reconnection
- Retry with exponential backoff

**Timeout (no notification):**
- Returns `None` from `get_status()`
- May indicate communication issues
- Trigger reconnection after consecutive failures

**Invalid payload:**
- First two bytes not recognized
- Raises `RuntimeError("Unrecognized payload")`

## Implementation Details

### Connection Setup:

```python
from bluepy.btle import Peripheral

# Connect to heater
peripheral = Peripheral(mac_address, "public")

# Get service and characteristic
service = peripheral.getServiceByUUID(service_uuid)
characteristic = service.getCharacteristics(characteristic_uuid)[0]

# Set notification delegate
peripheral.setDelegate(DieselHeaterDelegate(self))
```

### Sending Commands:

```python
def _send_command(self, command: int, argument: int, mode: int):
    # Build command array
    cmd = bytearray([0xAA, mode % 256, 0, 0, 0, 0, 0, 0])

    # Set authentication bytes
    if mode == 85:  # 0x55
        cmd[2] = self.passkey // 100
        cmd[3] = self.passkey % 100
    else:  # 136 (0x88)
        cmd[2] = random.randint(0, 255)
        cmd[3] = random.randint(0, 255)

    # Set command and argument
    cmd[4] = command % 256
    cmd[5] = argument % 256
    cmd[6] = argument // 256

    # Calculate checksum
    cmd[7] = sum(cmd[:7]) % 256

    # Write and wait for notification
    self.characteristic.write(cmd, withResponse=True)

    if self.peripheral.waitForNotifications(1.0):
        return self._last_notification
    return None
```

## Protocol Limitations

1. **No Encryption:** Beyond BLE pairing, data is not encrypted
2. **Simple Authentication:** 4-digit passkey is easily guessable
3. **No ACK:** Commands don't have explicit acknowledgment (status poll required)
4. **Single Client:** Heater can only maintain one BLE connection
5. **Short Timeout:** Must poll for notifications within 1 second
6. **No Buffering:** Rapid commands may be lost

## Reverse Engineering Notes

This protocol was reverse-engineered from:
- Official Vevor mobile app (Android/iOS)
- BLE packet captures
- Trial and error testing
- Community contributions

**Note:** Some fields remain unknown (marked with `?` in byte maps). Protocol version 136 (0x88) is not fully understood.

## References

- Original implementation: [bderleta/vevor-ble-bridge](https://github.com/bderleta/vevor-ble-bridge)
- bluepy library: [IanHarvey/bluepy](https://github.com/IanHarvey/bluepy)
