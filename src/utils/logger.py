"""
Logging system for the trading bot.
Provides comprehensive logging similar to the MQL5 EA.

This module re-exports all logging components from the logging package
for backward compatibility.
"""

# Import all logging components from the logging package
from src.utils.logging import (
    UTCFormatter,
    SymbolFileHandler,
    TradingLogger,
    get_logger,
    init_logger,
)

# Re-export all for backward compatibility
__all__ = [
    'UTCFormatter',
    'SymbolFileHandler',
    'TradingLogger',
    'get_logger',
    'init_logger',
]

