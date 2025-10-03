"""
Structured JSON logging configuration for AVM pipeline.
"""

import json
import logging
import time
from typing import Any, Dict, Optional
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "step": getattr(record, 'step', 'unknown'),
            "project": getattr(record, 'project', 'unknown'),
            "msg": record.getMessage(),
            "duration_ms": getattr(record, 'duration_ms', None),
            "extra": getattr(record, 'extra', {})
        }
        
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_entry)


def setup_logging(verbose: bool = False, quiet: bool = False, json_logs: bool = False) -> logging.Logger:
    """Setup logging configuration for AVM pipeline."""
    
    # Determine log level
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    
    # Create logger
    logger = logging.getLogger("avm")
    logger.setLevel(level)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(level)
    
    if json_logs:
        handler.setFormatter(JSONFormatter())
    else:
        # Simple console formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    return logger


def log_step(logger: logging.Logger, step: str, project: str, message: str, 
             duration_ms: Optional[float] = None, extra: Optional[Dict[str, Any]] = None):
    """Log a pipeline step with structured data."""
    
    extra_dict = extra or {}
    
    # Create a custom log record
    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None
    )
    
    # Add custom attributes
    record.step = step
    record.project = project
    if duration_ms is not None:
        record.duration_ms = duration_ms
    if extra_dict:
        record.extra = extra_dict
    
    logger.handle(record)


class Timer:
    """Context manager for timing operations."""
    
    def __init__(self, logger: logging.Logger, step: str, project: str, message: str):
        self.logger = logger
        self.step = step
        self.project = project
        self.message = message
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        self.logger.info(f"Starting {self.step}: {self.message}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration_ms = (time.time() - self.start_time) * 1000
            if exc_type is None:
                log_step(self.logger, self.step, self.project, 
                        f"Completed {self.step}: {self.message}", 
                        duration_ms=duration_ms)
            else:
                log_step(self.logger, self.step, self.project, 
                        f"Failed {self.step}: {self.message}", 
                        duration_ms=duration_ms)
