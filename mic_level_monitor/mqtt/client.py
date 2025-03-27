#!/usr/bin/env python3
"""
MQTT Client module for mic_level_monitor.
"""

import json
import time
import threading
import paho.mqtt.client as mqtt


class MQTTClient:
    """MQTT Client for microphone monitor."""

    def __init__(self, config, error_callback=None):
        """Initialize the MQTT client with the provided configuration."""
        self.config = config
        self.mqtt_connected = False
        self.mqtt_reconnecting = False
        self.reconnect_attempts = 0
        self.error_message = ""
        self.error_callback = error_callback
        self.mqtt_messages_sent = 0
        self.last_message_time = 0
        self.last_message = ""
        self.running = False

        # Initialize MQTT client with version 2 API
        self.mqtt_client = mqtt.Client(
            client_id=self.config["mqtt"]["client_id"],
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            clean_session=True,
        )

        # Set up MQTT callbacks
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect


    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties, *args):
        """Callback when connected to MQTT broker."""
        if reason_code == 0:
            self.mqtt_connected = True
            self.mqtt_reconnecting = False
            self.reconnect_attempts = 0
            self.error_message = ""
            
            # Publish online status message
            try:
                self.mqtt_client.publish(
                    "microphones/status",
                    payload=json.dumps({"status": "online"}),
                    qos=1,
                    retain=True
                )
            except Exception as e:
                self.error_message = f"Failed to publish online status: {e}"
        else:
            self.mqtt_connected = False
            self.error_message = f"Failed to connect to MQTT broker: {reason_code}"
            
        if self.error_callback:
            self.error_callback(self.error_message)

    def on_mqtt_disconnect(self, client, userdata, reason_code, properties, *args):
        """Callback when disconnected from MQTT broker."""
        self.mqtt_connected = False
        self.mqtt_reconnecting = True
        self.error_message = f"Disconnected from MQTT broker: {reason_code}"

        if self.error_callback:
            self.error_callback(self.error_message)

    def connect(self):
        """Connect to the MQTT broker."""
        try:
            # Configure automatic reconnection
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=10)

            # Set will message
            self.mqtt_client.will_set(
                "microphones/status",
                payload=json.dumps({"status": "offline"}),
                qos=1,
                retain=True,
            )

            # Connect with longer keepalive
            self.mqtt_client.connect_async(
                self.config["mqtt"]["broker"],
                self.config["mqtt"]["port"],
                keepalive=60,
            )
            self.mqtt_client.loop_start()

            return True
        except Exception as e:
            self.error_message = f"Failed to connect to MQTT broker: {e}"
            if self.error_callback:
                self.error_callback(self.error_message)
            return False

    def disconnect(self):
        """Disconnect from the MQTT broker."""
        # Publish online status message
        try:
            self.mqtt_client.publish(
                "microphones/status",
                payload=json.dumps({"status": "offline"}),
                qos=1,
                retain=True
            )
        except Exception as e:
            self.error_message = f"Failed to publish offline status: {e}"
    
        if self.error_callback:
            self.error_callback(self.error_message)
        self.running = False
        self.mqtt_client.loop_stop()
        if self.mqtt_client.is_connected():
            self.mqtt_client.disconnect()

    def publish(self, topic, payload):
        """Publish a message to a topic."""
        if not self.mqtt_connected:
            return False

        try:
            result = self.mqtt_client.publish(topic, payload)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.mqtt_messages_sent += 1
                self.last_message_time = time.time()
                self.last_message = f"{topic}: {payload}"
                return True
            else:
                self.error_message = f"MQTT publish failed with code: {result.rc}"
                if self.error_callback:
                    self.error_callback(self.error_message)
                return False
        except Exception as e:
            self.error_message = f"Error publishing to MQTT: {e}"
            if self.error_callback:
                self.error_callback(self.error_message)
            return False

    def force_reconnection(self):
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
            if self.error_callback:
                self.error_callback(self.error_message)

            return True
        except Exception as e:
            self.error_message = f"Reconnection failed: {e}"
            if self.error_callback:
                self.error_callback(self.error_message)
            return False

    def start_status_check(self):
        """Start a thread to monitor MQTT connection status."""
        self.running = True
        status_thread = threading.Thread(target=self._status_check_thread)
        status_thread.daemon = True
        status_thread.start()
        return status_thread

    def _status_check_thread(self):
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
                    if self.error_callback:
                        self.error_callback(self.error_message)

                    # After several consecutive failures, try to force reconnection
                    if disconnected_count == 5:  # Reduced for faster recovery
                        self.force_reconnection()
                        # Reset counter to prevent multiple rapid reconnect attempts
                        disconnected_count = 0

                time.sleep(2)

            except Exception as e:
                self.error_message = f"Connection check error: {e}"
                if self.error_callback:
                    self.error_callback(self.error_message)
                time.sleep(2)
