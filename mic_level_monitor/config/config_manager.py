#!/usr/bin/env python3
"""
Configuration Manager for Mic Level Monitor.
"""

import os
import toml
import pyaudio
from typing import Dict


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
