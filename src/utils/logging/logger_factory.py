"""
Logger factory for creating and managing the global logger instance.

This module guarantees a single TradingLogger instance across threads to
prevent duplicate handler attachments (which can cause duplicated log lines).
"""
from typing import Optional
import threading
from src.utils.logging.trading_logger import TradingLogger


# Global logger instance and creation lock (thread-safe singleton)
_logger: Optional[TradingLogger] = None
_logger_lock = threading.Lock()


def get_logger() -> TradingLogger:
    """Get the global logger instance (thread-safe)."""
    global _logger
    if _logger is None:
        # Double-checked locking to avoid race conditions during creation
        with _logger_lock:
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
                log_level: str = "INFO", enable_detailed: bool = True,
                use_async_logging: bool = True) -> TradingLogger:
    """
    Initialize or re-initialize the global logger (thread-safe).

    Args:
        log_to_file: Enable file logging
        log_to_console: Enable console logging
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        enable_detailed: Enable detailed logging
        use_async_logging: Enable async logging (background thread for I/O) - PERFORMANCE OPTIMIZATION

    Returns:
        TradingLogger instance
    """
    global _logger
    with _logger_lock:
        # Shutdown old logger if it exists
        if _logger is not None:
            try:
                _logger.shutdown()
            except:
                pass

        # Create a fresh TradingLogger. The constructor clears any existing
        # handlers on the underlying logging logger, so re-init is safe.
        _logger = TradingLogger(
            log_to_file=log_to_file,
            log_to_console=log_to_console,
            log_level=log_level,
            enable_detailed=enable_detailed,
            use_async_logging=use_async_logging
        )
        return _logger

