"""
MT5 price and spread information provider.
"""

import MetaTrader5 as mt5
from typing import Optional

from src.utils.logging import TradingLogger
from src.indicators.spread_indicator import SpreadIndicator


class PriceProvider:
    """Provides price and spread information from MT5"""

    def __init__(self, connection_manager, symbol_cache, logger: TradingLogger):
        """
        Initialize price provider.

        Args:
            connection_manager: ConnectionManager instance
            symbol_cache: SymbolInfoCache instance
            logger: Logger instance
        """
        self.connection_manager = connection_manager
        self.symbol_cache = symbol_cache
        self.logger = logger
        self.spread_indicator = SpreadIndicator()

    def get_current_price(self, symbol: str, price_type: str = 'bid') -> Optional[float]:
        """
        Get current price for symbol.

        Args:
            symbol: Symbol name
            price_type: 'bid' or 'ask'

        Returns:
            Current price or None
        """
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None

            return tick.bid if price_type == 'bid' else tick.ask

        except Exception as e:
            self.logger.error(f"Error getting price for {symbol}: {e}")
            return None

    def get_spread(self, symbol: str) -> Optional[float]:
        """
        Get current spread for symbol in points.

        Args:
            symbol: Symbol name

        Returns:
            Spread in points or None
        """
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None

            symbol_info = self.symbol_cache.get(symbol)
            if symbol_info is None:
                return None

            # Use SpreadIndicator for calculation
            spread_points = self.spread_indicator.calculate_spread_points(
                bid=tick.bid,
                ask=tick.ask,
                point=symbol_info['point']
            )

            return spread_points

        except Exception as e:
            self.logger.error(f"Error getting spread for {symbol}: {e}")
            return None

    def get_spread_percent(self, symbol: str) -> Optional[float]:
        """
        Get current spread as percentage of price.

        Args:
            symbol: Symbol name

        Returns:
            Spread as percentage (e.g., 0.05 = 0.05%) or None
        """
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None

            # Calculate spread as percentage of mid price
            spread_price = tick.ask - tick.bid
            mid_price = (tick.ask + tick.bid) / 2

            if mid_price == 0:
                return None

            spread_percent = (spread_price / mid_price) * 100

            return spread_percent

        except Exception as e:
            self.logger.error(f"Error getting spread percent for {symbol}: {e}")
            return None

