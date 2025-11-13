"""
MetaTrader 5 connection and data feed handler.
Manages connection to MT5 and provides real-time data for multiple symbols.

This module re-exports all MT5 components from the mt5 package
for backward compatibility.
"""

# Import all MT5 components from the mt5 package
from src.core.mt5 import (
    ConnectionManager,
    DataProvider,
    AccountInfoProvider,
    PositionProvider,
    PriceProvider,
    TradingStatusChecker,
    MarketWatchProvider,
    MT5Connector,
)

# Re-export all for backward compatibility
__all__ = [
    'ConnectionManager',
    'DataProvider',
    'AccountInfoProvider',
    'PositionProvider',
    'PriceProvider',
    'TradingStatusChecker',
    'MarketWatchProvider',
    'MT5Connector',
]

