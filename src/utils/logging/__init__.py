"""
Logging system for the trading bot.

This package contains logging components organized by responsibility
for better maintainability.
"""

# Re-export all logging components for convenient imports
from src.utils.logging.formatters import UTCFormatter
from src.utils.logging.handlers import SymbolFileHandler
from src.utils.logging.trading_logger import TradingLogger
from src.utils.logging.logger_factory import get_logger, init_logger
from src.utils.logging.time_provider import (
    get_time_provider,
    set_live_mode,
    set_backtest_mode,
    get_current_time,
    get_log_directory,
    is_backtest_mode,
)

__all__ = [
    'UTCFormatter',
    'SymbolFileHandler',
    'TradingLogger',
    'get_logger',
    'init_logger',
    'get_time_provider',
    'set_live_mode',
    'set_backtest_mode',
    'get_current_time',
    'get_log_directory',
    'is_backtest_mode',
]

