#!/usr/bin/env python3
"""
Core monitoring functionality for the microphone monitor.
"""

import json
import signal
import sys
import threading
import time
from typing import Dict, Optional

from rich.live import Live

from mic_level_monitor.config.config_manager import ConfigManager
from mic_level_monitor.audio.microphone import MicrophoneManager
from mic_level_monitor.mqtt.client import MQTTClient
from mic_level_monitor.ui.layout import MonitorUI


class MicrophoneMonitor:
    """Main monitor class that coordinates all components."""

    def __init__(self, config: Dict = None):
        """Initialize the microphone monitor with configuration."""
        # Load config, overriding with any provided values
        self.config = ConfigManager.load_config()
        if config:
            self._update_config(config)

        # Initialize components
        self.ui = MonitorUI(self.config)
        self.mic_manager = MicrophoneManager(self.config)
        self.mqtt_client = MQTTClient(self.config, self._handle_mqtt_error)

        # State variables
        self.running = False
        self.left_last_state = 0
        self.right_last_state = 0

    def _update_config(self, config: Dict) -> None:
        """Update the configuration with user provided values."""
        for section, values in config.items():
            if section in self.config and isinstance(values, dict):
                self.config[section].update(values)
            else:
                self.config[section] = values

    def _handle_mqtt_error(self, error_message: str) -> None:
        """Error handler callback for MQTT client."""
        self.ui.error_message = error_message
        self.ui.print_error(error_message)

    def print_input_devices(self) -> None:
        """Print all available audio input devices to the console."""
        devices = self.mic_manager.list_input_devices()
        self.ui.print_input_devices(devices)

    def setup_microphones(
        self, left_index: Optional[int] = None, right_index: Optional[int] = None
    ) -> None:
        """Set up the microphone streams."""
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
                    self.ui.console.input(
                        "[yellow]Enter the index for LEFT microphone: [/yellow]"
                    )
                )
            if right_index is None:
                right_index = int(
                    self.ui.console.input(
                        "[yellow]Enter the index for RIGHT microphone: [/yellow]"
                    )
                )

        # Save indices
        self.mic_manager.set_microphone_indices(left_index, right_index)

        # Save to config
        if "microphones" not in self.config:
            self.config["microphones"] = {}
        self.config["microphones"]["left_index"] = left_index
        self.config["microphones"]["right_index"] = right_index
        ConfigManager.save_config(self.config)

        # Update UI device names
        self.ui.set_device_names(
            self.mic_manager.get_device_name(left_index),
            self.mic_manager.get_device_name(right_index),
        )

        # Print selected microphones info
        self.ui.console.print(
            f"[green]Using LEFT mic:[/green] {self.mic_manager.get_device_name(left_index)}"
        )
        self.ui.console.print(
            f"[green]Using RIGHT mic:[/green] {self.mic_manager.get_device_name(right_index)}"
        )

    def publish_mic_state(self, topic: str, state: int, level: float) -> None:
        """Publish microphone state to MQTT topic."""
        payload = json.dumps(
            {"state": state, "level": float(level), "timestamp": time.time()}
        )
        if self.mqtt_client.publish(topic, payload):
            # Update UI state
            self.ui.update_state(
                mqtt_messages_sent=self.mqtt_client.mqtt_messages_sent,
                last_message_time=self.mqtt_client.last_message_time,
                last_message=self.mqtt_client.last_message,
            )

    def monitoring_thread(self) -> None:
        """Thread function to monitor microphones and publish to MQTT."""
        threshold = self.config["audio"]["threshold"]
        left_topic = self.config["mqtt"]["topics"]["left"]
        right_topic = self.config["mqtt"]["topics"]["right"]

        while self.running:
            try:
                # Read levels from both microphones
                left_level, right_level = self.mic_manager.read_levels()

                # Determine if levels exceed threshold
                left_active = 1 if left_level > threshold else 0
                right_active = 1 if right_level > threshold else 0

                # Update UI state
                self.ui.update_state(
                    left_level=left_level,
                    left_active=left_active,
                    right_level=right_level,
                    right_active=right_active,
                    mqtt_connected=self.mqtt_client.mqtt_connected,
                    mqtt_reconnecting=self.mqtt_client.mqtt_reconnecting,
                    reconnect_attempts=self.mqtt_client.reconnect_attempts,
                )

                # Only publish to MQTT if state changed or crossed threshold
                if self.mqtt_client.mqtt_connected:  # Only try to publish if connected
                    if left_active != self.left_last_state or left_active == 1:
                        self.publish_mic_state(left_topic, left_active, left_level)
                        self.left_last_state = left_active

                    if right_active != self.right_last_state or right_active == 1:
                        self.publish_mic_state(right_topic, right_active, right_level)
                        self.right_last_state = right_active

                # Short delay
                time.sleep(self.config["audio"]["check_interval"])

            except Exception as e:
                self.ui.error_message = f"Error monitoring: {e}"
                time.sleep(1)  # Prevent tight error loops

    def start_monitoring(self) -> None:
        """Start monitoring the microphones and display the TUI."""
        # Open audio streams
        if not self.mic_manager.open_streams():
            self.ui.print_error("Failed to open audio streams")
            return

        # Connect to MQTT broker
        self.mqtt_client.connect()

        # Start MQTT status check thread
        self.mqtt_client.start_status_check()

        self.running = True

        # Start the monitoring in a separate thread
        monitor_thread = threading.Thread(target=self.monitoring_thread)
        monitor_thread.daemon = True
        monitor_thread.start()

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
                self.ui.generate_layout(), refresh_per_second=5, screen=True
            ) as live:
                while self.running:
                    live.update(self.ui.generate_layout())
                    time.sleep(self.config["ui"]["refresh_rate"])
        except Exception as e:
            self.ui.error_message = f"Error in UI: {e}"
            self.ui.print_error(self.ui.error_message)
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Clean up resources."""
        self.running = False

        # Close audio streams
        self.mic_manager.close_streams()

        # Disconnect MQTT
        self.mqtt_client.disconnect()

        # Save config
        ConfigManager.save_config(self.config)

        self.ui.console.print("[yellow]Cleanup complete[/yellow]")
