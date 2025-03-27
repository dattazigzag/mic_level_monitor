"""
Dual Microphone MQTT Monitor Package.
This package monitors two USB microphones and publishes their status to MQTT topics.
"""
__version__ = "0.1.0"
# Expose key classes at the package level for convenience
from mic_level_monitor.monitoring.processor import MicrophoneMonitor