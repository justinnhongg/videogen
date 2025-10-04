"""
AVM Pipeline - Audio to Video Maker

A modular pipeline for converting narrated lessons into polished YouTube videos.
"""

__version__ = "1.0.0"
__author__ = "AVM Team"

from .errors import AVMError, TranscriptionError, RenderError, MuxError, ConfigError, ExitCode
from .config import load_merged_config, validate_config, get_config_value, set_config_value

__all__ = [
    "AVMError",
    "TranscriptionError", 
    "RenderError",
    "MuxError",
    "ConfigError",
    "ExitCode",
    "load_merged_config",
    "validate_config",
    "get_config_value",
    "set_config_value"
]
