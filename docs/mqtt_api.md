# Dual Microphone MQTT Monitor - API Documentation

This document describes the MQTT API for the Dual Microphone MQTT Monitor application, which publishes microphone activity to MQTT topics.

## Overview

The Microphone Monitor detects audio activity from two microphones (left and right) and publishes their status to MQTT topics when they cross a specified threshold or change state.

## MQTT Broker Setup

### Installing Mosquitto (recommended broker)

```bash
# macOS
brew install mosquitto
```

### Basic Broker Configuration

Edit `cat /opt/homebrew/etc/mosquitto/mosquitto.conf` (for macOS where `mosquitto` is installed via `homebrew`):

```conf
# Basic configuration allowing local connections
listener 1883
allow_anonymous true
```

### Launch mosquitto with default configuration

```bash
mosquitto
```

## MQTT Topics

### Microphone Status Topics

| Topic | Description |
|-------|-------------|
| `microphones/left` | Reports state and level of the left microphone |
| `microphones/right` | Reports state and level of the right microphone |

#### Payload Format

```json
{
  "state": 1,              // 0 = inactive, 1 = active
  "level": 532.45,         // Current audio level (float)
  "timestamp": 1743073094  // Unix timestamp when message was created
}
```

### System Topics

| Topic | Description |
|-------|-------------|
| `microphones/status` | LWT (Last Will and Testament) message topic |
| `microphones/ping` | Internal connectivity check |

#### Status Payload Format

```json
{
  "status": "offline"  // Only published when client disconnects abnormally
}
```

## Message Properties

| Property | Value | Description |
|----------|-------|-------------|
| QoS | 0 | For most messages (best effort delivery) |
| QoS | 1 | For Last Will and Testament messages |
| Retain | true | For Last Will messages |
| Retain | false | For all other messages |

## Frequency of Messages

- Messages are published when:
  - A microphone changes state (active to inactive or inactive to active)
  - A microphone is active (continuous updates with current level)
  - Default check interval: 0.2 seconds

## Monitoring MQTT Messages

You can monitor the MQTT topics using the mosquitto command-line client:

```bash
# Subscribe to all microphone topics
mosquitto_sub -h localhost -t 'microphones/#' -v

# Monitor just the left microphone
mosquitto_sub -h localhost -t 'microphones/left' -v
```

## Integration Examples

### Node-RED Flow Example

```json
[
  {
    "id": "a1b2c3d4e5",
    "type": "mqtt in",
    "topic": "microphones/+",
    "qos": "0",
    "datatype": "json",
    "wires": [
      ["f6g7h8i9j0"]
    ]
  },
  {
    "id": "f6g7h8i9j0",
    "type": "function",
    "name": "Process Microphone Data",
    "func": "const topic = msg.topic;\nconst isLeftMic = topic.endsWith('/left');\nconst isActive = msg.payload.state === 1;\n\nmsg.payload = {\n    microphone: isLeftMic ? 'left' : 'right',\n    active: isActive,\n    level: msg.payload.level,\n    timestamp: msg.payload.timestamp\n};\n\nreturn msg;",
    "wires": [
      ["k1l2m3n4o5"]
    ]
  }
]
```

## Understanding the Payload

The payload uses a simple JSON format for compatibility with most MQTT clients and platforms:

- **state**: Binary value (0/1) indicating if the microphone is currently detecting sound above the threshold
- **level**: Numeric value representing the current audio level (average absolute amplitude)
- **timestamp**: Unix timestamp allowing clients to determine message age

## Technical Implementation

The application uses Paho MQTT client library with the following features:

1. **Clean session**: Ensures no stale messages persist when reconnecting
2. **Will message**: Automatically publishes an offline status if disconnected abruptly
3. **QoS 0**: Used for regular level updates (prioritizes speed over guaranteed delivery)
4. **QoS 1**: Used for status messages (ensures delivery)
5. **Keepalive**: Set to 60 seconds to maintain connection with broker
6. **Automatic reconnection**: Built-in exponential backoff for connection retries

## Customization

Configuration options can be modified in `config.toml`:

```toml
[mqtt]
broker = "localhost"  # MQTT broker hostname/IP
port = 1883           # MQTT broker port
client_id = "mic_monitor"  # Client identifier 

[mqtt.topics]
left = "microphones/left"   # Topic for left microphone
right = "microphones/right" # Topic for right microphone
```
