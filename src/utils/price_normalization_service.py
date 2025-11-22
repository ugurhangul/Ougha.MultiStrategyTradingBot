"""
Price and Volume Normalization Service

Provides utilities for normalizing prices and volumes according to symbol specifications.
This service eliminates code duplication across OrderManager and RiskManager.
"""
from typing import Optional, Dict, Any
from src.core.mt5_connector import MT5Connector


class PriceNormalizationService:
    """
    Service for normalizing prices and volumes to symbol specifications.
    
    This class provides methods to:
    - Normalize prices to the correct number of decimal places (digits)
    - Normalize volumes to the correct lot step
    - Clamp volumes to min/max lot sizes
    - Validate normalized values
    """
    
    def __init__(self, connector: MT5Connector):
        """
        Initialize price normalization service.
        
        Args:
            connector: MT5 connector instance for retrieving symbol info
        """
        self.connector = connector
    
    def normalize_price(self, symbol: str, price: float) -> float:
        """
        Normalize price to symbol's digits (decimal places).

        Args:
            symbol: Symbol name
            price: Price to normalize

        Returns:
            Normalized price rounded to symbol's digits

        Examples:
            >>> service.normalize_price('EURUSD', 1.123456)
            1.12346  # Rounded to 5 digits for EURUSD
            >>> service.normalize_price('USDJPY', 110.123)
            110.12  # Rounded to 2 digits for USDJPY
        """
        info = self.connector.get_symbol_info(symbol)
        if info is None:
            # If symbol info not available, return price as-is
            return float(price)

        digits = info.get('digits', 5)  # Default to 5 digits if not specified
        return float(round(price, digits))
    
    def normalize_volume(self, symbol: str, volume: float) -> float:
        """
        Normalize volume to symbol's lot step and clamp to min/max.

        This method:
        1. Rounds volume to the nearest lot step
        2. Clamps the result to min_lot and max_lot

        Args:
            symbol: Symbol name
            volume: Volume (lot size) to normalize

        Returns:
            Normalized volume within symbol's lot constraints

        Examples:
            >>> service.normalize_volume('EURUSD', 0.03)
            0.01  # Rounded to lot_step=0.01
            >>> service.normalize_volume('EURUSD', 0.005)
            0.01  # Clamped to min_lot=0.01
        """
        info = self.connector.get_symbol_info(symbol)
        if info is None:
            # If symbol info not available, return volume as-is
            return float(volume)

        min_lot = info.get('min_lot', 0.01)
        max_lot = info.get('max_lot', 100.0)
        lot_step = info.get('lot_step', 0.01)

        # Round to lot step
        # Formula: round(volume / lot_step) * lot_step
        # Use Python's Decimal for precise rounding to avoid floating-point errors
        from decimal import Decimal, ROUND_HALF_UP

        # Convert to Decimal for precise calculation
        volume_decimal = Decimal(str(volume))
        lot_step_decimal = Decimal(str(lot_step))

        # Round to nearest lot step
        steps = (volume_decimal / lot_step_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        volume = float(steps * lot_step_decimal)

        # Clamp to min/max
        volume = max(min_lot, min(max_lot, volume))

        return float(volume)
    
    def normalize_stop_loss(self, symbol: str, sl: float, position_type: str) -> float:
        """
        Normalize stop loss price to symbol's digits.
        
        This is a convenience method that wraps normalize_price with
        additional context for stop loss levels.
        
        Args:
            symbol: Symbol name
            sl: Stop loss price
            position_type: 'BUY' or 'SELL'
            
        Returns:
            Normalized stop loss price
        """
        return self.normalize_price(symbol, sl)
    
    def normalize_take_profit(self, symbol: str, tp: float, position_type: str) -> float:
        """
        Normalize take profit price to symbol's digits.
        
        This is a convenience method that wraps normalize_price with
        additional context for take profit levels.
        
        Args:
            symbol: Symbol name
            tp: Take profit price
            position_type: 'BUY' or 'SELL'
            
        Returns:
            Normalized take profit price
        """
        return self.normalize_price(symbol, tp)
    
    def is_valid_volume(self, symbol: str, volume: float) -> bool:
        """
        Check if volume is valid for the symbol.
        
        Args:
            symbol: Symbol name
            volume: Volume to validate
            
        Returns:
            True if volume is within min/max and matches lot step, False otherwise
        """
        info = self.connector.get_symbol_info(symbol)
        if info is None:
            return False
        
        min_lot = info.get('min_lot', 0.01)
        max_lot = info.get('max_lot', 100.0)
        lot_step = info.get('lot_step', 0.01)
        
        # Check if within min/max
        if volume < min_lot or volume > max_lot:
            return False
        
        # Check if matches lot step (within floating point tolerance)
        remainder = abs(volume % lot_step)
        tolerance = lot_step * 0.01  # 1% tolerance for floating point errors
        
        return remainder < tolerance or abs(remainder - lot_step) < tolerance
    
    def get_symbol_constraints(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get all normalization constraints for a symbol.
        
        Args:
            symbol: Symbol name
            
        Returns:
            Dictionary with keys: digits, min_lot, max_lot, lot_step
            None if symbol info not available
            
        Examples:
            >>> service.get_symbol_constraints('EURUSD')
            {
                'digits': 5,
                'min_lot': 0.01,
                'max_lot': 100.0,
                'lot_step': 0.01
            }
        """
        info = self.connector.get_symbol_info(symbol)
        if info is None:
            return None
        
        return {
            'digits': info.get('digits', 5),
            'min_lot': info.get('min_lot', 0.01),
            'max_lot': info.get('max_lot', 100.0),
            'lot_step': info.get('lot_step', 0.01),
        }
    
    def calculate_lot_step_precision(self, symbol: str) -> int:
        """
        Calculate the number of decimal places for lot step.
        
        This is useful for formatting lot sizes in logs and UI.
        
        Args:
            symbol: Symbol name
            
        Returns:
            Number of decimal places for lot step (e.g., 2 for 0.01)
            
        Examples:
            >>> service.calculate_lot_step_precision('EURUSD')
            2  # lot_step=0.01 has 2 decimal places
            >>> service.calculate_lot_step_precision('BTCUSD')
            3  # lot_step=0.001 has 3 decimal places
        """
        info = self.connector.get_symbol_info(symbol)
        if info is None:
            return 2  # Default to 2 decimal places
        
        lot_step = info.get('lot_step', 0.01)
        
        # Convert to string and count decimal places
        lot_step_str = f"{lot_step:.10f}".rstrip('0')
        if '.' in lot_step_str:
            return len(lot_step_str.split('.')[1])
        else:
            return 0
    
    def format_volume(self, symbol: str, volume: float) -> str:
        """
        Format volume for display with appropriate precision.
        
        Args:
            symbol: Symbol name
            volume: Volume to format
            
        Returns:
            Formatted volume string
            
        Examples:
            >>> service.format_volume('EURUSD', 0.01)
            '0.01'
            >>> service.format_volume('BTCUSD', 0.001)
            '0.001'
        """
        precision = self.calculate_lot_step_precision(symbol)
        return f"{volume:.{precision}f}"
    
    def format_price(self, symbol: str, price: float) -> str:
        """
        Format price for display with appropriate precision.
        
        Args:
            symbol: Symbol name
            price: Price to format
            
        Returns:
            Formatted price string
            
        Examples:
            >>> service.format_price('EURUSD', 1.12345)
            '1.12345'
            >>> service.format_price('USDJPY', 110.123)
            '110.12'
        """
        info = self.connector.get_symbol_info(symbol)
        if info is None:
            return f"{price:.5f}"  # Default to 5 decimal places
        
        digits = info.get('digits', 5)
        return f"{price:.{digits}f}"

