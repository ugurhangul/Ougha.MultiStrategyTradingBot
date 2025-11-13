"""
Breakout and range detection utilities.

Provides utilities for detecting price ranges and validating breakouts
based on candle structure and price action.
"""
from typing import Optional, Dict, Any
from datetime import datetime


class RangeDetector:
    """
    Range detection utilities for breakout strategies.

    Detects and validates price ranges from reference candles.
    """

    @staticmethod
    def detect_range(candle_high: float, candle_low: float,
                    candle_time: datetime) -> Dict[str, Any]:
        """
        Detect range from a reference candle.

        Args:
            candle_high: Candle high price
            candle_low: Candle low price
            candle_time: Candle timestamp

        Returns:
            Dictionary with range information
        """
        range_size = candle_high - candle_low
        return {
            'high': candle_high,
            'low': candle_low,
            'range': range_size,
            'time': candle_time
        }

    @staticmethod
    def is_valid_range(range_high: float, range_low: float,
                      min_range_points: float = 0.0) -> bool:
        """
        Validate if range meets minimum size requirements.

        Args:
            range_high: Range high price
            range_low: Range low price
            min_range_points: Minimum range size in points

        Returns:
            True if range is valid
        """
        range_size = range_high - range_low
        return range_size >= min_range_points

    @staticmethod
    def get_range_boundaries(candle_data: Any, timeframe: str) -> Optional[Dict[str, float]]:
        """
        Get range boundaries from candle data.

        Args:
            candle_data: Candle data (DataFrame row or dict)
            timeframe: Timeframe identifier

        Returns:
            Dictionary with 'high' and 'low' keys, or None if invalid
        """
        try:
            if hasattr(candle_data, 'get'):
                return {
                    'high': candle_data.get('high'),
                    'low': candle_data.get('low')
                }
            else:
                return {
                    'high': candle_data['high'],
                    'low': candle_data['low']
                }
        except (KeyError, TypeError):
            return None


class BreakoutDetector:
    """
    Breakout detection utilities for breakout strategies.

    Detects valid breakouts and fakeouts based on candle structure.
    """

    @staticmethod
    def detect_breakout(range_high: float, range_low: float,
                       candle_open: float, candle_close: float) -> Optional[str]:
        """
        Detect if candle represents a valid breakout.

        CRITICAL: Valid breakout requires:
        - Candle open INSIDE range
        - Candle close OUTSIDE range

        Args:
            range_high: Range high price
            range_low: Range low price
            candle_open: Candle open price
            candle_close: Candle close price

        Returns:
            'BUY' for upward breakout, 'SELL' for downward breakout, None if no breakout
        """
        # Check if open is inside range
        open_inside_range = candle_open >= range_low and candle_open <= range_high

        if not open_inside_range:
            # Gap move - reject
            return None

        # Check for breakout above
        if candle_close > range_high:
            return 'BUY'

        # Check for breakout below
        if candle_close < range_low:
            return 'SELL'

        return None

    @staticmethod
    def is_valid_breakout(range_high: float, range_low: float,
                         candle_open: float, candle_close: float,
                         direction: str) -> bool:
        """
        Validate breakout criteria for specific direction.

        Args:
            range_high: Range high price
            range_low: Range low price
            candle_open: Candle open price
            candle_close: Candle close price
            direction: 'BUY' or 'SELL'

        Returns:
            True if breakout is valid
        """
        # Open must be inside range
        open_inside_range = candle_open >= range_low and candle_open <= range_high

        if not open_inside_range:
            return False

        # Check direction-specific close
        if direction == 'BUY':
            return candle_close > range_high
        elif direction == 'SELL':
            return candle_close < range_low

        return False

    @staticmethod
    def detect_fakeout(range_high: float, range_low: float,
                      breakout_close: float, current_close: float,
                      breakout_direction: str) -> bool:
        """
        Detect if price has reversed back into range (fakeout).

        Args:
            range_high: Range high price
            range_low: Range low price
            breakout_close: Close price of breakout candle
            current_close: Current close price
            breakout_direction: Original breakout direction ('BUY' or 'SELL')

        Returns:
            True if fakeout detected
        """
        if breakout_direction == 'BUY':
            # Broke above but reversed back below high
            return current_close < range_high
        elif breakout_direction == 'SELL':
            # Broke below but reversed back above low
            return current_close > range_low

        return False

    @staticmethod
    def get_breakout_direction(range_high: float, range_low: float,
                              candle_close: float) -> Optional[str]:
        """
        Get breakout direction based on close price.

        Args:
            range_high: Range high price
            range_low: Range low price
            candle_close: Candle close price

        Returns:
            'BUY' if above high, 'SELL' if below low, None if inside range
        """
        if candle_close > range_high:
            return 'BUY'
        elif candle_close < range_low:
            return 'SELL'
        return None

