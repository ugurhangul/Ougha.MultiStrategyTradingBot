"""
MT5 Market Watch provider.
"""

import MetaTrader5 as mt5
from typing import List

from src.utils.logging import TradingLogger
from src.constants import ERROR_MT5_NOT_CONNECTED


class MarketWatchProvider:
    """Provides Market Watch symbols from MT5"""

    def __init__(self, connection_manager, logger: TradingLogger):
        """
        Initialize Market Watch provider.

        Args:
            connection_manager: ConnectionManager instance
            logger: Logger instance
        """
        self.connection_manager = connection_manager
        self.logger = logger

    def get_market_watch_symbols(self) -> List[str]:
        """
        Get all symbols from MetaTrader's Market Watch list.

        Returns:
            List of symbol names currently in Market Watch
        """
        if not self.connection_manager.is_connected:
            self.logger.error(ERROR_MT5_NOT_CONNECTED)
            return []

        try:
            symbols = []
            total = mt5.symbols_total()

            if total == 0:
                self.logger.warning("No symbols found in Market Watch")
                return []

            # Get all symbols
            for i in range(total):
                symbol_info = mt5.symbol_info(mt5.symbols_get()[i].name)
                if symbol_info is not None and symbol_info.visible:
                    symbols.append(symbol_info.name)

            self.logger.info(f"Found {len(symbols)} symbols in Market Watch")
            return symbols

        except Exception as e:
            self.logger.error(f"Error getting Market Watch symbols: {e}")
            return []

