"""
Continuation and retest validation utilities.

Provides utilities for validating retest confirmation and continuation
patterns after breakouts.
"""
from typing import Optional
from src.indicators.pattern_extremes_indicator import PatternExtremesIndicator


class ContinuationValidator:
    """
    Continuation and retest validation utilities for breakout strategies.

    Validates retest confirmation and continuation patterns.
    """

    # Class-level indicator instance (shared across all calls)
    _extremes_indicator = PatternExtremesIndicator()

    @staticmethod
    def check_retest_confirmation(breakout_level: float, current_price: float,
                                  retest_range_percent: float = 0.001) -> bool:
        """
        Check if price has retested the breakout level.

        Args:
            breakout_level: The breakout level (range high or low)
            current_price: Current price
            retest_range_percent: Acceptable range for retest (default 0.1%)

        Returns:
            True if retest confirmed
        """
        retest_range = breakout_level * retest_range_percent
        return abs(current_price - breakout_level) <= retest_range

    @staticmethod
    def check_continuation_pattern(current_close: float, breakout_level: float,
                                   direction: str) -> bool:
        """
        Check if price continues in breakout direction after retest.

        Args:
            current_close: Current candle close price
            breakout_level: The breakout level (range high or low)
            direction: 'BUY' or 'SELL'

        Returns:
            True if continuation confirmed
        """
        if direction == 'BUY':
            return current_close > breakout_level
        elif direction == 'SELL':
            return current_close < breakout_level
        return False

    @staticmethod
    def find_highest_high_in_pattern(candles_df: any, reference_high: float) -> Optional[float]:
        """
        Find the HIGHEST HIGH among the last N candles.

        Uses confirmation candle timeframe (M5 for 4H_5M, M1 for 15M_1M).

        Args:
            candles_df: DataFrame with candle data (must have 'high' column)
            reference_high: Reference candle high (for logging)

        Returns:
            Highest high price, or None if no valid candles
        """
        if candles_df is None or len(candles_df) == 0:
            return None

        # Use PatternExtremesIndicator for calculation
        return ContinuationValidator._extremes_indicator.find_highest_high_from_dataframe(
            df=candles_df,
            period=None  # Use all candles in the DataFrame
        )

    @staticmethod
    def find_lowest_low_in_pattern(candles_df: any, reference_low: float) -> Optional[float]:
        """
        Find the LOWEST LOW among the last N candles.

        Uses confirmation candle timeframe (M5 for 4H_5M, M1 for 15M_1M).

        Args:
            candles_df: DataFrame with candle data (must have 'low' column)
            reference_low: Reference candle low (for logging)

        Returns:
            Lowest low price, or None if no valid candles
        """
        if candles_df is None or len(candles_df) == 0:
            return None

        # Use PatternExtremesIndicator for calculation
        return ContinuationValidator._extremes_indicator.find_lowest_low_from_dataframe(
            df=candles_df,
            period=None  # Use all candles in the DataFrame
        )

