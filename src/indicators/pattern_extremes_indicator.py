"""
Pattern Extremes Indicator

Finds highest highs and lowest lows in price patterns.
Used for continuation pattern validation and breakout analysis.

Uses TA-Lib MAX/MIN functions for optimized performance when period is specified.
"""
import pandas as pd
import numpy as np
import talib
from typing import Optional
from src.utils.logger import get_logger


class PatternExtremesIndicator:
    """
    Pattern extremes detection indicator.
    
    Identifies the highest high and lowest low within a specified pattern or period.
    Used for:
    - Continuation pattern validation
    - Support/resistance level identification
    - Breakout confirmation
    """
    
    def __init__(self):
        """Initialize pattern extremes indicator."""
        self.logger = get_logger()
    
    def find_highest_high(
        self,
        highs: pd.Series,
        period: Optional[int] = None
    ) -> Optional[float]:
        """
        Find the highest high in the data.

        Uses TA-Lib MAX function for optimized performance when period is specified.
        Falls back to pandas max() when period is None (all data).

        Args:
            highs: Series of high prices
            period: Number of recent candles to analyze (None = all)

        Returns:
            Highest high price or None if no data
        """
        if highs is None or len(highs) == 0:
            return None

        try:
            if period is not None and period > 0:
                # Use TA-Lib MAX for fixed period (optimized C library)
                if len(highs) < period:
                    # Not enough data for the specified period
                    return None

                max_values = talib.MAX(highs.values, timeperiod=period)
                highest = max_values[-1]
            else:
                # Use pandas max() for all data (no period limit)
                highest = highs.max()

            return float(highest) if not pd.isna(highest) else None

        except (KeyError, AttributeError, ValueError) as e:
            self.logger.error(f"Error finding highest high: {e}")
            return None
    
    def find_lowest_low(
        self,
        lows: pd.Series,
        period: Optional[int] = None
    ) -> Optional[float]:
        """
        Find the lowest low in the data.

        Uses TA-Lib MIN function for optimized performance when period is specified.
        Falls back to pandas min() when period is None (all data).

        Args:
            lows: Series of low prices
            period: Number of recent candles to analyze (None = all)

        Returns:
            Lowest low price or None if no data
        """
        if lows is None or len(lows) == 0:
            return None

        try:
            if period is not None and period > 0:
                # Use TA-Lib MIN for fixed period (optimized C library)
                if len(lows) < period:
                    # Not enough data for the specified period
                    return None

                min_values = talib.MIN(lows.values, timeperiod=period)
                lowest = min_values[-1]
            else:
                # Use pandas min() for all data (no period limit)
                lowest = lows.min()

            return float(lowest) if not pd.isna(lowest) else None

        except (KeyError, AttributeError, ValueError) as e:
            self.logger.error(f"Error finding lowest low: {e}")
            return None
    
    def find_highest_high_from_dataframe(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None
    ) -> Optional[float]:
        """
        Find highest high from DataFrame with 'high' column.
        
        Args:
            df: DataFrame with OHLC data
            period: Number of recent candles to analyze (None = all)
        
        Returns:
            Highest high price or None if no data
        """
        if df is None or len(df) == 0:
            return None
        
        try:
            return self.find_highest_high(df['high'], period)
        except (KeyError, AttributeError) as e:
            self.logger.error(f"Error accessing 'high' column: {e}")
            return None
    
    def find_lowest_low_from_dataframe(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None
    ) -> Optional[float]:
        """
        Find lowest low from DataFrame with 'low' column.
        
        Args:
            df: DataFrame with OHLC data
            period: Number of recent candles to analyze (None = all)
        
        Returns:
            Lowest low price or None if no data
        """
        if df is None or len(df) == 0:
            return None
        
        try:
            return self.find_lowest_low(df['low'], period)
        except (KeyError, AttributeError) as e:
            self.logger.error(f"Error accessing 'low' column: {e}")
            return None
    
    def find_extremes(
        self,
        highs: pd.Series,
        lows: pd.Series,
        period: Optional[int] = None
    ) -> dict:
        """
        Find both highest high and lowest low.
        
        Args:
            highs: Series of high prices
            lows: Series of low prices
            period: Number of recent candles to analyze (None = all)
        
        Returns:
            Dictionary with 'highest_high' and 'lowest_low'
        """
        return {
            'highest_high': self.find_highest_high(highs, period),
            'lowest_low': self.find_lowest_low(lows, period)
        }
    
    def find_extremes_from_dataframe(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None
    ) -> dict:
        """
        Find both highest high and lowest low from DataFrame.
        
        Args:
            df: DataFrame with OHLC data
            period: Number of recent candles to analyze (None = all)
        
        Returns:
            Dictionary with 'highest_high' and 'lowest_low'
        """
        return {
            'highest_high': self.find_highest_high_from_dataframe(df, period),
            'lowest_low': self.find_lowest_low_from_dataframe(df, period)
        }

