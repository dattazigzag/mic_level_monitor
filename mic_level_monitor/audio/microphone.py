#!/usr/bin/env python3
"""
Audio processing and microphone management for the microphone monitor.
"""

import numpy as np
import pyaudio
from typing import Dict, List, Optional, Tuple


class MicrophoneManager:
    """Manages audio devices and streams."""

    def __init__(self, config: Dict):
        """Initialize the microphone manager with configuration."""
        self.config = config
        self.p = pyaudio.PyAudio()
        self.left_mic_index = None
        self.right_mic_index = None
        self.left_stream = None
        self.right_stream = None

    def __del__(self):
        """Clean up resources when object is deleted."""
        self.close_streams()
        if hasattr(self, "p") and self.p:
            self.p.terminate()

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

    def set_microphone_indices(self, left_index: int, right_index: int) -> None:
        """Set the microphone indices for left and right channels."""
        self.left_mic_index = left_index
        self.right_mic_index = right_index

    def get_device_name(self, index: int) -> str:
        """Get the name of a device by index."""
        try:
            return self.p.get_device_info_by_index(index)["name"]
        except Exception:
            return "Unknown Device"

    def open_streams(self) -> bool:
        """Open audio streams for both microphones."""
        if self.left_mic_index is None or self.right_mic_index is None:
            return False

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

            return True
        except Exception as e:
            print(f"Error opening audio streams: {e}")
            self.close_streams()
            return False

    def close_streams(self) -> None:
        """Close audio streams."""
        if hasattr(self, "left_stream") and self.left_stream:
            try:
                self.left_stream.stop_stream()
                self.left_stream.close()
            except Exception:
                pass
            self.left_stream = None

        if hasattr(self, "right_stream") and self.right_stream:
            try:
                self.right_stream.stop_stream()
                self.right_stream.close()
            except Exception:
                pass
            self.right_stream = None

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
            print(f"Error reading microphone data: {e}")
            return 0.0

    def read_levels(self) -> Tuple[float, float]:
        """Read levels from both microphones."""
        left_level = self.read_mic_level(self.left_stream) if self.left_stream else 0.0
        right_level = (
            self.read_mic_level(self.right_stream) if self.right_stream else 0.0
        )
        return left_level, right_level
