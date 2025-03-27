#!/usr/bin/env python3
"""
Dual Microphone MQTT Monitor with Terminal User Interface (TUI)

This script monitors two USB microphones and publishes their status to MQTT topics
when they cross a specified audio threshold level, with a clean terminal interface.
"""

import argparse
import json
import os
import signal
import sys
import time
import threading
import toml
from typing import Dict, List, Optional, Tuple

import numpy as np
import paho.mqtt.client as mqtt
import pyaudio
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.table import Table
from rich.progress_bar import ProgressBar
from rich.style import Style


class ConfigManager:
    """Manages loading and saving configuration from/to TOML files."""

    DEFAULT_CONFIG_FILE = "default_config.toml"
    USER_CONFIG_FILE = "config.toml"

    @staticmethod
    def get_default_config():
        """Return the default configuration as a dictionary."""
        # Define static default config as fallback
        default_config = {
            "mqtt": {
                "broker": "localhost",
                "port": 1883,
                "client_id": "mic_monitor",
                "topics": {"left": "microphones/left", "right": "microphones/right"},
            },
            "audio": {
                "chunk_size": 1024,
                "sample_format": pyaudio.paInt16,
                "channels": 1,
                "rate": 44100,
                "threshold": 500,
                "check_interval": 0.2,
            },
            "ui": {"refresh_rate": 0.1},
        }
        return default_config

    @staticmethod
    def _convert_sample_format(format_code):
        """Convert numeric sample format code to pyaudio constant."""
        format_map = {
            8: pyaudio.paInt8,
            16: pyaudio.paInt16,
            24: pyaudio.paInt24,
            32: pyaudio.paInt32,
            33: pyaudio.paFloat32,
            34: pyaudio.paInt24,
        }
        return format_map.get(format_code, pyaudio.paInt16)

    @staticmethod
    def _convert_sample_format_to_code(format_const):
        """Convert pyaudio constant to numeric code for storage."""
        format_map = {
            pyaudio.paInt8: 8,
            pyaudio.paInt16: 16,
            pyaudio.paInt24: 24,
            pyaudio.paInt32: 32,
            pyaudio.paFloat32: 33,
        }
        return format_map.get(format_const, 16)

    @classmethod
    def load_config(cls):
        """Load configuration from TOML file with fallback to defaults."""
        config = cls.get_default_config()

        # Try to load default config file
        if os.path.exists(cls.DEFAULT_CONFIG_FILE):
            try:
                with open(cls.DEFAULT_CONFIG_FILE, "r") as f:
                    default_from_file = toml.load(f)
                    # Merge with defaults
                    cls._merge_configs(config, default_from_file)
            except Exception as e:
                print(f"Error loading default config file: {e}")

        # Try to load user config file (overrides defaults)
        if os.path.exists(cls.USER_CONFIG_FILE):
            try:
                with open(cls.USER_CONFIG_FILE, "r") as f:
                    user_config = toml.load(f)
                    # Merge with base config
                    cls._merge_configs(config, user_config)
            except Exception as e:
                print(f"Error loading user config file: {e}")

        # Convert numeric sample format to pyaudio constant
        if "audio" in config and "sample_format" in config["audio"]:
            if isinstance(config["audio"]["sample_format"], int):
                config["audio"]["sample_format"] = cls._convert_sample_format(
                    config["audio"]["sample_format"]
                )

        return config

    @classmethod
    def save_config(cls, config):
        """Save configuration to TOML file."""
        # Create a copy of the config to modify before saving
        save_config = cls._create_saveable_config(config)

        try:
            with open(cls.USER_CONFIG_FILE, "w") as f:
                toml.dump(save_config, f)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    @classmethod
    def _create_saveable_config(cls, config):
        """Create a copy of config suitable for saving to TOML."""
        # Deep copy the config
        import copy

        save_config = copy.deepcopy(config)

        # Convert pyaudio constant to numeric code
        if "audio" in save_config and "sample_format" in save_config["audio"]:
            save_config["audio"]["sample_format"] = cls._convert_sample_format_to_code(
                save_config["audio"]["sample_format"]
            )

        return save_config

    @staticmethod
    def _merge_configs(base_config, override_config):
        """Recursively merge override_config into base_config."""
        for key, value in override_config.items():
            if (
                key in base_config
                and isinstance(base_config[key], dict)
                and isinstance(value, dict)
            ):
                # Recursively merge nested dictionaries
                ConfigManager._merge_configs(base_config[key], value)
            else:
                # Override or add value
                base_config[key] = value

        return base_config

    @classmethod
    def create_default_config_file(cls):
        """Create a default config file if it doesn't exist."""
        if not os.path.exists(cls.DEFAULT_CONFIG_FILE):
            config = cls.get_default_config()
            saveable_config = cls._create_saveable_config(config)

            try:
                with open(cls.DEFAULT_CONFIG_FILE, "w") as f:
                    toml.dump(saveable_config, f)
                return True
            except Exception as e:
                print(f"Error creating default config file: {e}")
                return False
        return False


class MicrophoneMonitorTUI:
    """Monitor multiple microphones with a Terminal User Interface."""

    def __init__(self, config: Dict = None):
        """Initialize the microphone monitor with the provided configuration."""
        # Load config from file first
        self.config = ConfigManager.load_config()

        # Override with any command line config
        if config:
            self._update_config(config)

        # Initialize PyAudio
        self.p = pyaudio.PyAudio()

        # Initialize MQTT client with version 2 API
        self.mqtt_client = mqtt.Client(
            client_id=self.config["mqtt"]["client_id"],
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )

        # Set up MQTT callbacks
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect

        # Microphone state variables
        self.left_mic_index: Optional[int] = None
        self.right_mic_index: Optional[int] = None
        self.left_stream = None
        self.right_stream = None
        self.left_last_state = 0
        self.right_last_state = 0

        # Data for UI display
        self.left_level = 0.0
        self.left_active = 0
        self.right_level = 0.0
        self.right_active = 0
        self.mqtt_connected = False
        self.mqtt_messages_sent = 0
        self.last_message_time = 0
        self.last_message = ""
        self.mqtt_reconnecting = False
        self.reconnect_attempts = 0

        # Status flags
        self.running = False
        self.error_message = ""

        # Rich console setup
        self.console = Console()

    def _update_config(self, config: Dict) -> None:
        """Update the configuration with user provided values."""
        for section, values in config.items():
            if section in self.config and isinstance(values, dict):
                self.config[section].update(values)
            else:
                self.config[section] = values

    def save_current_config(self):
        """Save the current configuration to a file."""
        # Save any microphone indices if they were selected
        if self.left_mic_index is not None:
            if "microphones" not in self.config:
                self.config["microphones"] = {}
            self.config["microphones"]["left_index"] = self.left_mic_index

        if self.right_mic_index is not None:
            if "microphones" not in self.config:
                self.config["microphones"] = {}
            self.config["microphones"]["right_index"] = self.right_mic_index

        # Save config to file
        return ConfigManager.save_config(self.config)

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties, *args):
        """Callback when connected to MQTT broker."""
        if reason_code == 0:
            self.mqtt_connected = True
            self.mqtt_reconnecting = False
            self.reconnect_attempts = 0
            self.error_message = ""
        else:
            self.mqtt_connected = False
            self.error_message = f"Failed to connect to MQTT broker: {reason_code}"

    def on_mqtt_disconnect(self, client, userdata, reason_code, properties, *args):
        """Callback when disconnected from MQTT broker."""
        self.mqtt_connected = False
        self.mqtt_reconnecting = True  # Set the reconnecting flag for UI
        self.error_message = f"Disconnected from MQTT broker: {reason_code}"

    def force_mqtt_reconnection(self):
        """Force MQTT client to disconnect and reconnect with proper cleanup."""
        try:
            # Stop the network loop
            self.mqtt_client.loop_stop()

            # Force disconnect if still connected
            try:
                self.mqtt_client.disconnect()
            except:
                pass

            # Clear connection state
            self.mqtt_connected = False
            self.mqtt_reconnecting = True
            self.reconnect_attempts += 1

            # Give network sockets time to close
            time.sleep(1)

            # Create a new client instance to ensure clean state
            self.mqtt_client = mqtt.Client(
                client_id=f"{self.config['mqtt']['client_id']}_{int(time.time())}",
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                clean_session=True,
            )

            # Set up MQTT callbacks
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect

            # Reconfigure client
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

            # Set will message
            self.mqtt_client.will_set(
                "microphones/status",
                payload=json.dumps({"status": "offline"}),
                qos=1,
                retain=True,
            )

            # Try to connect
            self.mqtt_client.connect_async(
                self.config["mqtt"]["broker"], self.config["mqtt"]["port"], keepalive=60
            )

            # Restart network loop
            self.mqtt_client.loop_start()

            self.error_message = (
                f"Forcing reconnection (attempt {self.reconnect_attempts})..."
            )
        except Exception as e:
            self.error_message = f"Reconnection failed: {e}"

    def mqtt_status_check_thread(self):
        """Thread to actively verify MQTT connection status."""
        disconnected_count = 0

        while self.running:
            try:
                # Get current reported state
                reported_connected = self.mqtt_client.is_connected()

                if reported_connected:
                    # If client reports connected, try a simple publish to verify
                    try:
                        result = self.mqtt_client.publish(
                            "microphones/ping", "ping", qos=0
                        )
                        if result.rc == mqtt.MQTT_ERR_SUCCESS:
                            # Successful publish request
                            self.mqtt_connected = True
                            disconnected_count = 0
                            self.mqtt_reconnecting = False
                        else:
                            # Failed to send publish request
                            disconnected_count += 1
                    except:
                        # Exception during publish
                        disconnected_count += 1
                else:
                    # Client reports not connected
                    disconnected_count += 1
                    self.mqtt_connected = False

                # Update UI status based on disconnection count
                if disconnected_count >= 3:
                    self.mqtt_connected = False
                    self.error_message = "Disconnected from MQTT broker"

                    # After several consecutive failures, try to force reconnection
                    if disconnected_count == 5:  # Reduced from 10 for faster recovery
                        self.force_mqtt_reconnection()
                        # Reset counter to prevent multiple rapid reconnect attempts
                        disconnected_count = 0

                time.sleep(2)

            except Exception as e:
                self.error_message = f"Connection check error: {e}"
                time.sleep(2)

    def list_input_devices(self) -> List[Dict]:
        """List all available audio input devices."""
        input_devices = []

        for i in range(self.p.get_device_count()):
            dev_info = self.p.get_device_info_by_index(i)
            if dev_info["maxInputChannels"] > 0:
                input_devices.append(
                    {
                        "index": i,
                        "name": dev_info["name"],
                        "channels": dev_info["maxInputChannels"],
                        "sample_rate": int(dev_info["defaultSampleRate"]),
                    }
                )

        return input_devices

    def print_input_devices(self) -> None:
        """Print all available input devices to the console."""
        devices = self.list_input_devices()
        self.console.print("[bold]Available input devices:[/bold]")
        table = Table(show_header=True)
        table.add_column("Index", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Channels", style="magenta")
        table.add_column("Sample Rate", style="yellow")

        for device in devices:
            table.add_row(
                str(device["index"]),
                device["name"],
                str(device["channels"]),
                f"{device['sample_rate']} Hz",
            )

        self.console.print(table)

    def setup_microphones(
        self, left_index: int = None, right_index: int = None
    ) -> None:
        """
        Set up the microphone streams.

        If indices are not provided, try to load from config or prompt user.
        """
        # Try to get mic indices from config if not provided
        if (
            left_index is None
            and "microphones" in self.config
            and "left_index" in self.config["microphones"]
        ):
            left_index = self.config["microphones"]["left_index"]

        if (
            right_index is None
            and "microphones" in self.config
            and "right_index" in self.config["microphones"]
        ):
            right_index = self.config["microphones"]["right_index"]

        # Continue with normal setup if we still don't have indices
        if left_index is None or right_index is None:
            self.print_input_devices()

            if left_index is None:
                left_index = int(
                    self.console.input(
                        "[yellow]Enter the index for LEFT microphone: [/yellow]"
                    )
                )
            if right_index is None:
                right_index = int(
                    self.console.input(
                        "[yellow]Enter the index for RIGHT microphone: [/yellow]"
                    )
                )

        self.left_mic_index = left_index
        self.right_mic_index = right_index

        # Save the selected indices to config
        self.save_current_config()

        # Print selected microphones info
        self.console.print(
            f"[green]Using LEFT mic:[/green] {self.p.get_device_info_by_index(self.left_mic_index)['name']}"
        )
        self.console.print(
            f"[green]Using RIGHT mic:[/green] {self.p.get_device_info_by_index(self.right_mic_index)['name']}"
        )

    def setup_mqtt(self) -> None:
        """Set up the MQTT client connection."""
        try:
            # Create MQTT client with clean session
            self.mqtt_client = mqtt.Client(
                client_id=self.config["mqtt"]["client_id"],
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                clean_session=True,
            )

            # Set up MQTT callbacks
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect

            # Configure automatic reconnection
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=10)

            # Set will message
            self.mqtt_client.will_set(
                "microphones/status",
                payload=json.dumps({"status": "offline"}),
                qos=1,
                retain=True,
            )

            # Longer keepalive (60 seconds instead of 5)
            self.mqtt_client.connect_async(
                self.config["mqtt"]["broker"],
                self.config["mqtt"]["port"],
                keepalive=60,
            )
            self.mqtt_client.loop_start()

            self.console.print(
                f"[green]Connecting to MQTT broker at {self.config['mqtt']['broker']}:{self.config['mqtt']['port']}[/green]"
            )
        except Exception as e:
            self.error_message = f"Failed to connect to MQTT broker: {e}"
            self.console.print(f"[bold red]{self.error_message}[/bold red]")

    def open_audio_streams(self) -> None:
        """Open the audio streams for both microphones."""
        try:
            audio_config = self.config["audio"]

            self.left_stream = self.p.open(
                format=audio_config["sample_format"],
                channels=audio_config["channels"],
                rate=audio_config["rate"],
                input=True,
                input_device_index=self.left_mic_index,
                frames_per_buffer=audio_config["chunk_size"],
            )

            self.right_stream = self.p.open(
                format=audio_config["sample_format"],
                channels=audio_config["channels"],
                rate=audio_config["rate"],
                input=True,
                input_device_index=self.right_mic_index,
                frames_per_buffer=audio_config["chunk_size"],
            )

            self.console.print("[green]Audio streams opened successfully[/green]")
        except Exception as e:
            self.error_message = f"Error opening audio streams: {e}"
            self.console.print(f"[bold red]{self.error_message}[/bold red]")
            self.cleanup()
            sys.exit(1)

    def read_mic_level(self, stream) -> float:
        """Read the audio level from a microphone stream."""
        try:
            audio_data = np.frombuffer(
                stream.read(
                    self.config["audio"]["chunk_size"], exception_on_overflow=False
                ),
                dtype=np.int16,
            )
            # Calculate volume level (absolute mean)
            level = np.abs(audio_data).mean()
            return level
        except Exception as e:
            self.error_message = f"Error reading microphone data: {e}"
            return 0.0

    def publish_mic_state(self, topic: str, state: int, level: float) -> None:
        """Publish microphone state to MQTT topic."""
        if not self.mqtt_connected:
            return  # Skip publishing if not connected

        try:
            payload = json.dumps(
                {"state": state, "level": float(level), "timestamp": time.time()}
            )
            result = self.mqtt_client.publish(topic, payload)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.mqtt_messages_sent += 1
                self.last_message_time = time.time()
                self.last_message = f"{topic}: {state} (Level: {level:.2f})"
            else:
                self.error_message = f"MQTT publish failed with code: {result.rc}"
        except Exception as e:
            self.error_message = f"Error publishing to MQTT: {e}"

    def generate_layout(self) -> Layout:
        """Generate the TUI layout."""
        layout = Layout()

        # Split into header, body, and footer
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )

        # Split body into left and right columns
        layout["body"].split_row(Layout(name="left_mic"), Layout(name="right_mic"))

        # Create header content
        header_text = Text()
        header_text.append("Dual Microphone MQTT Monitor", style="bold white")
        header_text.append(
            f" | MQTT Broker: {self.config['mqtt']['broker']}:{self.config['mqtt']['port']}"
        )

        # Determine connection status and appropriate styling
        if self.mqtt_reconnecting:
            status = f"RECONNECTING (Attempt {self.reconnect_attempts})"
            status_style = "yellow"
        else:
            status = "CONNECTED" if self.mqtt_connected else "DISCONNECTED"
            status_style = "green" if self.mqtt_connected else "red"

        # Determine header color based on connection status
        if self.mqtt_connected:
            header_style = "white on blue"
        elif self.mqtt_reconnecting:
            header_style = "white on yellow"
        else:
            header_style = "white on red"

        header_text.append(f" | Status: ", style="white")
        header_text.append(status, style=status_style)
        header_text.append(f" | Messages Sent: {self.mqtt_messages_sent}")

        # Use dynamic header style for the panel
        layout["header"].update(Panel(header_text, style=header_style))

        # Create mic panels
        threshold = self.config["audio"]["threshold"]
        max_level = threshold * 4  # For visualization scaling

        # Left mic panel
        left_panel = Table.grid(expand=True)
        left_panel.add_column()
        left_panel.add_row(
            f"LEFT MICROPHONE: {self.p.get_device_info_by_index(self.left_mic_index)['name']}"
        )

        left_state_text = "ACTIVE" if self.left_active else "INACTIVE"
        left_state_style = "green" if self.left_active else "blue"
        left_panel.add_row(Text(f"State: {left_state_text}", style=left_state_style))
        left_panel.add_row(f"Level: {self.left_level:.2f}")

        # Progress bar for left mic
        left_bar_style = "green" if self.left_level > threshold else "blue"
        left_progress = ProgressBar(
            total=max_level,
            completed=min(self.left_level, max_level),
            style=left_bar_style,
        )
        left_panel.add_row(left_progress)

        # Right mic panel
        right_panel = Table.grid(expand=True)
        right_panel.add_column()
        right_panel.add_row(
            f"RIGHT MICROPHONE: {self.p.get_device_info_by_index(self.right_mic_index)['name']}"
        )

        right_state_text = "ACTIVE" if self.right_active else "INACTIVE"
        right_state_style = "green" if self.right_active else "blue"
        right_panel.add_row(Text(f"State: {right_state_text}", style=right_state_style))
        right_panel.add_row(f"Level: {self.right_level:.2f}")

        # Progress bar for right mic
        right_bar_style = "green" if self.right_level > threshold else "blue"
        right_progress = ProgressBar(
            total=max_level,
            completed=min(self.right_level, max_level),
            style=right_bar_style,
        )
        right_panel.add_row(right_progress)

        layout["left_mic"].update(Panel(left_panel, title="Left Microphone"))
        layout["right_mic"].update(Panel(right_panel, title="Right Microphone"))

        # Create footer with last message and help text
        footer_text = Text()
        if self.last_message:
            time_diff = time.time() - self.last_message_time
            footer_text.append(
                f"Last Message ({time_diff:.1f}s ago): {self.last_message}"
            )
        else:
            footer_text.append("No messages sent yet")

        if self.error_message:
            footer_text.append(f"\nSTATUS: {self.error_message}", style="bold red")

        layout["footer"].update(Panel(footer_text, title="Status"))

        return layout

    def monitoring_thread(self) -> None:
        """Thread function to monitor microphones and publish to MQTT."""
        threshold = self.config["audio"]["threshold"]
        left_topic = self.config["mqtt"]["topics"]["left"]
        right_topic = self.config["mqtt"]["topics"]["right"]

        while self.running:
            try:
                # Read levels from both microphones
                self.left_level = self.read_mic_level(self.left_stream)
                self.right_level = self.read_mic_level(self.right_stream)

                # Determine if levels exceed threshold
                self.left_active = 1 if self.left_level > threshold else 0
                self.right_active = 1 if self.right_level > threshold else 0

                # Only publish to MQTT if state changed or crossed threshold
                if self.mqtt_connected:  # Only try to publish if connected
                    if (
                        self.left_active != self.left_last_state
                        or self.left_active == 1
                    ):
                        self.publish_mic_state(
                            left_topic, self.left_active, self.left_level
                        )
                        self.left_last_state = self.left_active

                    if (
                        self.right_active != self.right_last_state
                        or self.right_active == 1
                    ):
                        self.publish_mic_state(
                            right_topic, self.right_active, self.right_level
                        )
                        self.right_last_state = self.right_active

                # Short delay
                time.sleep(self.config["audio"]["check_interval"])

            except Exception as e:
                self.error_message = f"Error monitoring: {e}"
                time.sleep(1)  # Prevent tight error loops

    def start_monitoring(self) -> None:
        """Start monitoring the microphones and display the TUI."""
        if not self.left_stream or not self.right_stream:
            self.open_audio_streams()

        if not self.mqtt_client.is_connected():
            self.setup_mqtt()

        self.running = True

        # Start the monitoring in a separate thread
        monitor_thread = threading.Thread(target=self.monitoring_thread)
        monitor_thread.daemon = True
        monitor_thread.start()

        # Start connection status monitoring thread
        status_thread = threading.Thread(target=self.mqtt_status_check_thread)
        status_thread.daemon = True
        status_thread.start()

        # Set up signal handler to gracefully exit on Ctrl+C
        def handle_signal(sig, frame):
            self.running = False
            time.sleep(0.5)  # Give monitoring thread time to exit
            self.cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_signal)

        # Start the live display
        try:
            with Live(
                self.generate_layout(), refresh_per_second=5, screen=True
            ) as live:
                while self.running:
                    live.update(self.generate_layout())
                    time.sleep(self.config["ui"]["refresh_rate"])
        except Exception as e:
            self.error_message = f"Error in UI: {e}"
            self.console.print(f"[bold red]{self.error_message}[/bold red]")
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Clean up resources."""
        self.running = False

        # Close audio streams
        if hasattr(self, "left_stream") and self.left_stream:
            self.left_stream.stop_stream()
            self.left_stream.close()

        if hasattr(self, "right_stream") and self.right_stream:
            self.right_stream.stop_stream()
            self.right_stream.close()

        # Terminate PyAudio
        if hasattr(self, "p"):
            self.p.terminate()

        # Disconnect MQTT
        if hasattr(self, "mqtt_client"):
            self.mqtt_client.loop_stop()
            if self.mqtt_client.is_connected():
                self.mqtt_client.disconnect()

        # Save any config changes
        self.save_current_config()

        self.console.print("[yellow]Cleanup complete[/yellow]")


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Dual Microphone MQTT Monitor")
    parser.add_argument("--broker", type=str, help="MQTT broker address")
    parser.add_argument("--port", type=int, help="MQTT broker port")
    parser.add_argument("--left-mic", type=int, help="Index of left microphone")
    parser.add_argument("--right-mic", type=int, help="Index of right microphone")
    parser.add_argument("--threshold", type=int, help="Audio level threshold")
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio devices and exit",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to custom config file (default: config.toml)",
    )
    parser.add_argument(
        "--create-default-config",
        action="store_true",
        help="Create default config file and exit",
    )

    return parser.parse_args()


def main():
    """Main function."""

    args = parse_arguments()

    # Create default config file if requested
    if args.create_default_config:
        if ConfigManager.create_default_config_file():
            print(
                f"Default configuration created in {ConfigManager.DEFAULT_CONFIG_FILE}"
            )
        else:
            print("Failed to create default configuration file")
        return

    # Use custom config file if provided
    if args.config:
        ConfigManager.USER_CONFIG_FILE = args.config

    # Create custom config from arguments
    config = {}
    if args.broker or args.port:
        config["mqtt"] = {}
        if args.broker:
            config["mqtt"]["broker"] = args.broker
        if args.port:
            config["mqtt"]["port"] = args.port

    if args.threshold:
        config["audio"] = {"threshold": args.threshold}

    # Initialize monitor
    monitor = MicrophoneMonitorTUI(config)

    # Just list devices if requested
    if args.list_devices:
        monitor.print_input_devices()
        return

    # Setup and start monitoring
    monitor.setup_microphones(args.left_mic, args.right_mic)
    monitor.start_monitoring()


if __name__ == "__main__":
    main()
