"""
MetaTrader 5 connection and data feed components.

This package provides specialized components for MT5 integration,
including connection management, data retrieval, and trading status checks.
"""

from src.core.mt5.connection_manager import ConnectionManager
from src.core.mt5.data_provider import DataProvider
from src.core.mt5.account_info_provider import AccountInfoProvider
from src.core.mt5.position_provider import PositionProvider
from src.core.mt5.price_provider import PriceProvider
from src.core.mt5.trading_status_checker import TradingStatusChecker
from src.core.mt5.market_watch_provider import MarketWatchProvider
from src.core.mt5.mt5_connector import MT5Connector

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

