"""
Logger factory for creating and managing the global logger instance.
"""
from typing import Optional
from src.utils.logging.trading_logger import TradingLogger


# Global logger instance
_logger: Optional[TradingLogger] = None


def get_logger() -> TradingLogger:
    """Get the global logger instance"""
    global _logger
    if _logger is None:
        from src.config import config
        _logger = TradingLogger(
            log_to_file=config.logging.log_to_file,
            log_to_console=config.logging.log_to_console,
            log_level=config.logging.log_level,
            enable_detailed=config.logging.enable_detailed_logging
        )
    return _logger


def init_logger(log_to_file: bool = True, log_to_console: bool = True,
                log_level: str = "INFO", enable_detailed: bool = True) -> TradingLogger:
    """Initialize the global logger"""
    global _logger
    _logger = TradingLogger(
        log_to_file=log_to_file,
        log_to_console=log_to_console,
        log_level=log_level,
        enable_detailed=enable_detailed
    )
    return _logger

