"""
AVM Pipeline - Audio to Video Maker

A modular pipeline for converting narrated lessons into polished YouTube videos.
"""

__version__ = "1.0.0"
__author__ = "AVM Team"

from .errors import AVMError, TranscriptionError, RenderError, MuxError, ConfigError

__all__ = [
    "AVMError",
    "TranscriptionError", 
    "RenderError",
    "MuxError",
    "ConfigError"
]
