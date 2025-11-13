"""
Logging configuration settings.
"""
from dataclasses import dataclass


@dataclass
class LoggingConfig:
    """Logging settings"""
    enable_detailed_logging: bool = True
    log_to_file: bool = True
    log_to_console: bool = True
    log_level: str = "INFO"
    log_active_trades_every_5min: bool = True

