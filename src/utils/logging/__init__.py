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

__all__ = [
    'UTCFormatter',
    'SymbolFileHandler',
    'TradingLogger',
    'get_logger',
    'init_logger',
]

