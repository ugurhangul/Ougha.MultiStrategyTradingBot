"""
MT5 account information provider.
"""

import MetaTrader5 as mt5
from typing import Optional

from src.utils.logging import TradingLogger
from src.utils.currency_conversion_service import CurrencyConversionService


class AccountInfoProvider:
    """Provides account information from MT5"""

    def __init__(self, connection_manager, logger: TradingLogger):
        """
        Initialize account info provider.

        Args:
            connection_manager: ConnectionManager instance
            logger: Logger instance
        """
        self.connection_manager = connection_manager
        self.logger = logger
        self.currency_service = CurrencyConversionService(logger)

    def get_account_balance(self) -> float:
        """Get current account balance"""
        if not self.connection_manager.is_connected:
            return 0.0

        account_info = mt5.account_info()
        return account_info.balance if account_info else 0.0

    def get_account_equity(self) -> float:
        """Get current account equity"""
        if not self.connection_manager.is_connected:
            return 0.0

        account_info = mt5.account_info()
        return account_info.equity if account_info else 0.0

    def get_account_free_margin(self) -> Optional[float]:
        """Get current account free margin (available for new positions)"""
        if not self.connection_manager.is_connected:
            return None

        account_info = mt5.account_info()
        return account_info.margin_free if account_info else None

    def get_account_currency(self) -> str:
        """Get account currency"""
        if not self.connection_manager.is_connected:
            return ""

        account_info = mt5.account_info()
        return account_info.currency if account_info else ""

    def calculate_margin(self, symbol: str, volume: float, price: float) -> Optional[float]:
        """
        Calculate required margin for opening a position.

        Uses MT5's order_calc_margin() to get accurate margin requirements.

        Args:
            symbol: Symbol name (e.g., 'EURUSD')
            volume: Lot size (e.g., 0.1)
            price: Entry price

        Returns:
            Required margin in account currency, or None if calculation fails
        """
        if not self.connection_manager.is_connected:
            return None

        # Use MT5's built-in margin calculation
        # order_calc_margin(action, symbol, volume, price)
        # action: ORDER_TYPE_BUY (0) or ORDER_TYPE_SELL (1)
        # We use BUY as margin is typically the same for both
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, volume, price)

        if margin is None or margin < 0:
            return None

        return margin

    def get_currency_conversion_rate(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Get conversion rate from one currency to another.

        Delegates to CurrencyConversionService.

        Args:
            from_currency: Source currency (e.g., 'THB')
            to_currency: Target currency (e.g., 'USD')

        Returns:
            Conversion rate or None if not available
        """
        return self.currency_service.get_conversion_rate(from_currency, to_currency)

