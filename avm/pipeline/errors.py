"""
Custom exceptions and exit codes for AVM pipeline.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes for AVM CLI."""
    SUCCESS = 0
    INVALID_PROJECT = 10
    FFMPEG_MISSING = 11
    CHROMIUM_MISSING = 12
    TRANSCRIPTION_FAILURE = 13
    RENDER_FAILURE = 14
    MUX_FAILURE = 15
    CONFIG_PARSE_ERROR = 16
    UNKNOWN_ERROR = 20


class AVMError(Exception):
    """Base exception for AVM pipeline errors."""
    
    def __init__(self, message: str, exit_code: ExitCode = ExitCode.UNKNOWN_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


class TranscriptionError(AVMError):
    """Error during audio transcription."""
    
    def __init__(self, message: str):
        super().__init__(message, ExitCode.TRANSCRIPTION_FAILURE)


class RenderError(AVMError):
    """Error during video rendering."""
    
    def __init__(self, message: str):
        super().__init__(message, ExitCode.RENDER_FAILURE)


class MuxError(AVMError):
    """Error during video/audio muxing."""
    
    def __init__(self, message: str):
        super().__init__(message, ExitCode.MUX_FAILURE)


class ConfigError(AVMError):
    """Error parsing configuration files."""
    
    def __init__(self, message: str):
        super().__init__(message, ExitCode.CONFIG_PARSE_ERROR)
