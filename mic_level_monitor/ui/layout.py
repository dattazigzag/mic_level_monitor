#!/usr/bin/env python3
"""
Terminal User Interface components for the microphone monitor.
"""

import time
from typing import Dict

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.progress_bar import ProgressBar


class MonitorUI:
    """Terminal User Interface for the microphone monitor."""

    def __init__(self, config: Dict):
        """Initialize the UI with configuration."""
        self.config = config
        self.console = Console()

        # State for UI display
        self.left_level = 0.0
        self.left_active = 0
        self.right_level = 0.0
        self.right_active = 0
        self.mqtt_connected = False
        self.mqtt_reconnecting = False
        self.reconnect_attempts = 0
        self.mqtt_messages_sent = 0
        self.last_message_time = 0
        self.last_message = ""
        self.error_message = ""

        # Device names
        self.left_device_name = "Unknown"
        self.right_device_name = "Unknown"

    def set_device_names(self, left_name: str, right_name: str) -> None:
        """Set the device names for display."""
        self.left_device_name = left_name
        self.right_device_name = right_name

    def update_state(self, **kwargs) -> None:
        """Update the UI state with provided values."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def print_input_devices(self, devices: list) -> None:
        """Print all available input devices to the console."""
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
        left_panel.add_row(f"LEFT MICROPHONE: {self.left_device_name}")

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
        right_panel.add_row(f"RIGHT MICROPHONE: {self.right_device_name}")

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

    def print_error(self, message: str) -> None:
        """Print an error message."""
        self.console.print(f"[bold red]{message}[/bold red]")
