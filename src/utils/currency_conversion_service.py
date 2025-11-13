"""
Currency Conversion Service

Provides currency conversion utilities to eliminate duplication between
MT5Connector and RiskManager.
"""
from typing import Optional, TYPE_CHECKING
import MetaTrader5 as mt5
from src.constants import CURRENCY_SEPARATORS

if TYPE_CHECKING:
    from src.utils.logger import TradingLogger


class CurrencyConversionService:
    """
    Service for currency conversion operations.

    This class provides methods to:
    - Get conversion rates between currency pairs
    - Try multiple pair formats (direct, inverse, with separators)
    - Convert tick values to account currency
    - Handle conversion failures gracefully
    """

    def __init__(self, logger: 'TradingLogger'):
        """
        Initialize currency conversion service.
        
        Args:
            logger: Logger instance for logging conversion operations
        """
        self.logger = logger
    
    def get_conversion_rate(
        self,
        from_currency: str,
        to_currency: str
    ) -> Optional[float]:
        """
        Get conversion rate from one currency to another.
        
        Tries multiple formats:
        1. Direct pair: FROMTO (e.g., THBUSD)
        2. Inverse pair: TOFROM (e.g., USDTHB)
        3. Pairs with separators: FROM/TO, FROM.TO, FROM_TO
        
        Args:
            from_currency: Source currency (e.g., 'THB')
            to_currency: Target currency (e.g., 'USD')
            
        Returns:
            Conversion rate or None if not available
            
        Examples:
            >>> service.get_conversion_rate('USD', 'EUR')
            0.92  # 1 USD = 0.92 EUR
            >>> service.get_conversion_rate('EUR', 'USD')
            1.09  # 1 EUR = 1.09 USD
        """
        # Same currency - no conversion needed
        if from_currency == to_currency:
            return 1.0
        
        # Try direct pair: FROMTO (e.g., THBUSD)
        rate = self._try_direct_pair(from_currency, to_currency)
        if rate is not None:
            return rate
        
        # Try inverse pair: TOFROM (e.g., USDTHB)
        rate = self._try_inverse_pair(from_currency, to_currency)
        if rate is not None:
            return rate
        
        # Try with common separators
        rate = self._try_with_separators(from_currency, to_currency)
        if rate is not None:
            return rate
        
        # All attempts failed
        self.logger.warning(
            f"Could not find conversion rate for {from_currency} to {to_currency}. "
            f"Tried: {from_currency}{to_currency}, {to_currency}{from_currency}, and variants with separators"
        )
        return None
    
    def convert_tick_value(
        self,
        tick_value: float,
        currency_profit: str,
        account_currency: str,
        symbol: str
    ) -> tuple[float, Optional[float]]:
        """
        Convert tick value to account currency.
        
        Args:
            tick_value: Original tick value
            currency_profit: Profit currency of the symbol
            account_currency: Account currency
            symbol: Symbol name for logging
            
        Returns:
            Tuple of (converted_tick_value, conversion_rate)
            If no conversion needed or failed, returns (original_tick_value, None)
            
        Examples:
            >>> service.convert_tick_value(10.0, 'EUR', 'USD', 'EURUSD')
            (10.92, 1.092)  # Converted from EUR to USD
        """
        # No conversion needed
        if currency_profit == account_currency:
            return tick_value, None
        
        # Missing currency information
        if not account_currency or currency_profit == 'UNKNOWN':
            return tick_value, None
        
        # Get conversion rate
        conversion_rate = self.get_conversion_rate(currency_profit, account_currency)
        
        if conversion_rate is not None:
            converted_tick_value = tick_value * conversion_rate
            
            self.logger.info(
                f"Currency conversion applied: {currency_profit} -> {account_currency}, "
                f"Rate={conversion_rate:.5f}, TickValue: {tick_value:.5f} -> {converted_tick_value:.5f}",
                symbol
            )
            
            return converted_tick_value, conversion_rate
        else:
            self.logger.error(
                f"Failed to get conversion rate from {currency_profit} to {account_currency}. "
                f"Using original tick value - risk calculation may be incorrect!",
                symbol
            )
            return tick_value, None
    
    def _try_direct_pair(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Try direct currency pair (e.g., EURUSD for EUR->USD).
        
        Args:
            from_currency: Source currency
            to_currency: Target currency
            
        Returns:
            Conversion rate or None
        """
        direct_pair = f"{from_currency}{to_currency}"
        tick = mt5.symbol_info_tick(direct_pair)
        
        if tick is not None:
            # Use bid price for conversion
            return tick.bid
        
        return None
    
    def _try_inverse_pair(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Try inverse currency pair (e.g., USDEUR for EUR->USD).
        
        Args:
            from_currency: Source currency
            to_currency: Target currency
            
        Returns:
            Conversion rate or None
        """
        inverse_pair = f"{to_currency}{from_currency}"
        tick = mt5.symbol_info_tick(inverse_pair)
        
        if tick is not None:
            # Use inverse of ask price for conversion
            if tick.ask > 0:
                return 1.0 / tick.ask
        
        return None
    
    def _try_with_separators(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Try currency pairs with various separators.
        
        Tries: FROM/TO, FROM.TO, FROM_TO
        
        Args:
            from_currency: Source currency
            to_currency: Target currency
            
        Returns:
            Conversion rate or None
        """
        for separator in CURRENCY_SEPARATORS:
            if not separator:  # Skip empty separator (already tried)
                continue
            
            # Try direct pair with separator
            direct_pair_sep = f"{from_currency}{separator}{to_currency}"
            tick = mt5.symbol_info_tick(direct_pair_sep)
            if tick is not None:
                return tick.bid
            
            # Try inverse pair with separator
            inverse_pair_sep = f"{to_currency}{separator}{from_currency}"
            tick = mt5.symbol_info_tick(inverse_pair_sep)
            if tick is not None:
                if tick.ask > 0:
                    return 1.0 / tick.ask
        
        return None
    
    def format_conversion_log(
        self,
        from_currency: str,
        to_currency: str,
        rate: float,
        original_value: float,
        converted_value: float
    ) -> str:
        """
        Format a conversion log message.
        
        Args:
            from_currency: Source currency
            to_currency: Target currency
            rate: Conversion rate
            original_value: Original value
            converted_value: Converted value
            
        Returns:
            Formatted log message
            
        Examples:
            >>> service.format_conversion_log('EUR', 'USD', 1.092, 100.0, 109.2)
            'Converted 100.00 EUR to 109.20 USD (rate: 1.09200)'
        """
        return (
            f"Converted {original_value:.2f} {from_currency} to "
            f"{converted_value:.2f} {to_currency} (rate: {rate:.5f})"
        )
    
    def is_conversion_needed(
        self,
        currency_profit: str,
        account_currency: str
    ) -> bool:
        """
        Check if currency conversion is needed.
        
        Args:
            currency_profit: Profit currency of the symbol
            account_currency: Account currency
            
        Returns:
            True if conversion is needed, False otherwise
        """
        if not account_currency or currency_profit == 'UNKNOWN':
            return False
        
        return currency_profit != account_currency

