#!/usr/bin/env python3
"""
Dual Microphone MQTT Monitor - Main Entry Point.

This script initializes and runs the microphone monitor application.
"""

import argparse
import sys

from mic_level_monitor.config.config_manager import ConfigManager
from mic_level_monitor.monitoring.processor import MicrophoneMonitor


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
        return 0

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
    monitor = MicrophoneMonitor(config)

    # Just list devices if requested
    if args.list_devices:
        monitor.print_input_devices()
        return 0

    # Setup and start monitoring
    monitor.setup_microphones(args.left_mic, args.right_mic)
    monitor.start_monitoring()

    return 0


if __name__ == "__main__":
    sys.exit(main())
