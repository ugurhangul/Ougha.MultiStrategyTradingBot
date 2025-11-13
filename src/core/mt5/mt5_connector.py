"""
MetaTrader 5 connection and data feed handler.
Manages connection to MT5 and provides real-time data for multiple symbols.
"""

import pandas as pd
from typing import List, Optional, Tuple

from src.models.data_models import CandleData, PositionInfo
from src.config.configs import MT5Config
from src.utils.logger import get_logger
from src.core.symbol_info_cache import SymbolInfoCache

from src.core.mt5.connection_manager import ConnectionManager
from src.core.mt5.data_provider import DataProvider
from src.core.mt5.account_info_provider import AccountInfoProvider
from src.core.mt5.position_provider import PositionProvider
from src.core.mt5.price_provider import PriceProvider
from src.core.mt5.trading_status_checker import TradingStatusChecker
from src.core.mt5.market_watch_provider import MarketWatchProvider


class MT5Connector:
    """
    Manages connection to MetaTrader 5 and data retrieval.

    This is a facade class that delegates to specialized components:
    - ConnectionManager: Handles connection and disconnection
    - DataProvider: Provides candle data
    - AccountInfoProvider: Provides account information
    - PositionProvider: Provides position information
    - PriceProvider: Provides price and spread information
    - TradingStatusChecker: Checks trading status
    - MarketWatchProvider: Provides Market Watch symbols
    """

    def __init__(self, config: MT5Config):
        """
        Initialize MT5 connector.

        Args:
            config: MT5 configuration
        """
        self.config = config
        self.logger = get_logger()
        self.symbol_cache = SymbolInfoCache(self.logger)

        # Initialize specialized components
        self.connection_manager = ConnectionManager(config, self.logger)
        self.data_provider = DataProvider(self.connection_manager, self.logger)
        self.account_info_provider = AccountInfoProvider(self.connection_manager, self.logger)
        self.position_provider = PositionProvider(self.connection_manager, self.logger)
        self.price_provider = PriceProvider(self.connection_manager, self.symbol_cache, self.logger)
        self.trading_status_checker = TradingStatusChecker(self.connection_manager, self.symbol_cache, self.logger)
        self.market_watch_provider = MarketWatchProvider(self.connection_manager, self.logger)

    @property
    def is_connected(self) -> bool:
        """Check if connected to MT5"""
        return self.connection_manager.is_connected

    def connect(self) -> bool:
        """Connect to MetaTrader 5. Delegates to ConnectionManager."""
        return self.connection_manager.connect()

    def disconnect(self):
        """Disconnect from MetaTrader 5. Delegates to ConnectionManager."""
        self.connection_manager.disconnect()

    def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
        """Get historical candles. Delegates to DataProvider."""
        return self.data_provider.get_candles(symbol, timeframe, count)

    def get_latest_candle(self, symbol: str, timeframe: str) -> Optional[CandleData]:
        """Get the latest closed candle. Delegates to DataProvider."""
        return self.data_provider.get_latest_candle(symbol, timeframe)

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Get symbol information (cached). Delegates to SymbolInfoCache."""
        return self.symbol_cache.get(symbol)

    def clear_symbol_info_cache(self, symbol: Optional[str] = None):
        """Clear symbol info cache. Delegates to SymbolInfoCache."""
        self.symbol_cache.invalidate(symbol)

    def get_account_balance(self) -> float:
        """Get current account balance. Delegates to AccountInfoProvider."""
        return self.account_info_provider.get_account_balance()

    def get_account_equity(self) -> float:
        """Get current account equity. Delegates to AccountInfoProvider."""
        return self.account_info_provider.get_account_equity()

    def get_account_currency(self) -> str:
        """Get account currency. Delegates to AccountInfoProvider."""
        return self.account_info_provider.get_account_currency()

    def get_currency_conversion_rate(self, from_currency: str, to_currency: str) -> Optional[float]:
        """Get conversion rate. Delegates to AccountInfoProvider."""
        return self.account_info_provider.get_currency_conversion_rate(from_currency, to_currency)

    def get_positions(self, symbol: Optional[str] = None, magic_number: Optional[int] = None) -> List[PositionInfo]:
        """Get open positions. Delegates to PositionProvider."""
        return self.position_provider.get_positions(symbol, magic_number)

    def get_closed_position_info(self, ticket: int) -> Optional[Tuple[str, float, float, str]]:
        """Get closed position info. Delegates to PositionProvider."""
        return self.position_provider.get_closed_position_info(ticket)

    def get_current_price(self, symbol: str, price_type: str = 'bid') -> Optional[float]:
        """Get current price. Delegates to PriceProvider."""
        return self.price_provider.get_current_price(symbol, price_type)

    def get_spread(self, symbol: str) -> Optional[float]:
        """Get spread in points. Delegates to PriceProvider."""
        return self.price_provider.get_spread(symbol)

    def get_spread_percent(self, symbol: str) -> Optional[float]:
        """Get spread as percentage. Delegates to PriceProvider."""
        return self.price_provider.get_spread_percent(symbol)

    def is_autotrading_enabled(self) -> bool:
        """Check if AutoTrading is enabled. Delegates to TradingStatusChecker."""
        return self.trading_status_checker.is_autotrading_enabled()

    def is_trading_enabled(self, symbol: str) -> bool:
        """Check if trading is enabled for symbol. Delegates to TradingStatusChecker."""
        return self.trading_status_checker.is_trading_enabled(symbol)

    def is_market_open(self, symbol: str) -> bool:
        """Check if market is open. Delegates to TradingStatusChecker."""
        return self.trading_status_checker.is_market_open(symbol)

    def is_in_trading_session(self, symbol: str) -> bool:
        """Check if symbol is in active trading session. Delegates to TradingStatusChecker."""
        return self.trading_status_checker.is_in_trading_session(symbol)

    def get_market_watch_symbols(self) -> List[str]:
        """Get Market Watch symbols. Delegates to MarketWatchProvider."""
        return self.market_watch_provider.get_market_watch_symbols()

