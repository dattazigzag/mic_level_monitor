# Configuration Reference

This document details all configuration options available for the Mic Level Monitor application.

## Configuration Files

The application uses two TOML configuration files:

- `default_config.toml`: Contains default settings, shouldn't be modified directly
- `config.toml`: User settings that override defaults

## MQTT Settings

```toml
[mqtt]
broker = "localhost"           # MQTT broker hostname or IP address
port = 1883                    # MQTT broker port
client_id = "mic_monitor"      # Client identifier for MQTT connection

[mqtt.topics]
left = "microphones/left"      # Topic for left microphone state
right = "microphones/right"    # Topic for right microphone state
```

## Audio Settings

```toml
[audio]
chunk_size = 1024              # Audio buffer size in samples
sample_format = 16             # Audio format: 8, 16, 24, or 32 bits, 33 for float32
channels = 1                   # Number of audio channels per device
rate = 44100                   # Sample rate in Hz
threshold = 500                # Audio level threshold for activation
check_interval = 0.2           # Time between audio level checks in seconds
```

| Setting | Default | Description |
|---------|---------|-------------|
| chunk_size | 1024 | Number of audio frames per buffer read. Smaller values reduce latency but increase CPU usage. |
| sample_format | 16 | Audio sample format code (16 = 16-bit integer, 33 = 32-bit float). |
| threshold | 500 | Level that must be exceeded for the microphone to be considered "active". Higher values make detection less sensitive. |

## UI Settings

```toml
[ui]
refresh_rate = 0.1             # Terminal UI refresh rate in seconds
```

## Microphone Settings

```toml
[microphones]
left_index = 1                 # Device index for left microphone
right_index = 2                # Device index for right microphone
```

These settings are saved automatically when you select microphones with the application.

## Advanced Options

### Finding the Right Threshold

The threshold setting determines when a microphone is considered "active". Finding the right value:

1. Start with the default (500)
2. Run with the `--list-devices` option to identify your microphones
3. Start the monitor and observe noise levels in normal conditions
4. Adjust threshold to be just above background noise level

Example for adjusting threshold:

```bash
# Test with a higher threshold (less sensitive)
mic-monitor --threshold 800

# Test with a lower threshold (more sensitive)
mic-monitor --threshold 300
```

### Performance Tuning

For better performance on lower-powered systems:

```toml
[audio]
chunk_size = 2048              # Larger buffer reduces CPU usage
check_interval = 0.5           # Less frequent checks
rate = 22050                   # Lower sample rate

[ui]
refresh_rate = 0.2             # Less frequent UI updates
```
