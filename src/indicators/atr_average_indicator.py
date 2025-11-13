"""
ATR Average Indicator

Calculates average ATR (Average True Range) over multiple periods.
Useful for volatility filtering and adaptive stop loss calculations.

Uses TA-Lib SMA function for optimized averaging of ATR values.
"""
import pandas as pd
import numpy as np
from typing import Optional, List
import talib
from src.utils.logger import get_logger


class ATRAverageIndicator:
    """
    Average ATR indicator.
    
    Calculates the average of multiple ATR values over a specified period.
    This provides a smoothed volatility measure that can be used for:
    - Volatility filtering (comparing current ATR to average ATR)
    - Adaptive stop loss calculations
    - Market condition assessment
    """
    
    def __init__(self):
        """Initialize ATR average indicator."""
        self.logger = get_logger()
    
    def calculate_atr(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> Optional[float]:
        """
        Calculate single ATR value.
        
        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of close prices
            period: ATR period (default: 14)
        
        Returns:
            Current ATR value or None if insufficient data
        """
        if len(high) < period + 1 or len(low) < period + 1 or len(close) < period + 1:
            return None
        
        try:
            atr_values = talib.ATR(high.values, low.values, close.values, timeperiod=period)
            current_atr = atr_values[-1]
            
            if np.isnan(current_atr):
                return None
            
            return float(current_atr)
        
        except Exception as e:
            self.logger.error(f"Error calculating ATR: {e}")
            return None
    
    def calculate_average_atr(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        atr_period: int = 14,
        average_period: int = 20
    ) -> Optional[float]:
        """
        Calculate average ATR over multiple periods using TA-Lib SMA.

        Uses a rolling Simple Moving Average (SMA) of ATR values for optimized performance.
        This is more efficient than the legacy manual loop method.

        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of close prices
            atr_period: Period for ATR calculation (default: 14)
            average_period: Number of ATR values to average (default: 20)

        Returns:
            Average ATR value or None if insufficient data
        """
        required_data = average_period + atr_period
        if len(high) < required_data or len(low) < required_data or len(close) < required_data:
            self.logger.warning(
                f"Not enough data for average ATR: need {required_data}, have {len(close)}"
            )
            return None

        try:
            # Step 1: Calculate ATR series using TA-Lib
            atr_series = talib.ATR(
                high.values,
                low.values,
                close.values,
                timeperiod=atr_period
            )

            # Step 2: Apply SMA to ATR series for rolling average
            avg_atr_series = talib.SMA(atr_series, timeperiod=average_period)

            # Step 3: Get the most recent average ATR value
            avg_atr = avg_atr_series[-1]

            # Check for NaN (insufficient data or calculation error)
            if np.isnan(avg_atr):
                return None

            return float(avg_atr)

        except Exception as e:
            self.logger.error(f"Error calculating average ATR: {e}")
            return None

    def calculate_average_atr_legacy(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        atr_period: int = 14,
        average_period: int = 20
    ) -> Optional[float]:
        """
        Calculate average ATR using legacy manual loop method.

        DEPRECATED: This method is kept for backward compatibility testing only.
        Use calculate_average_atr() instead for better performance.

        Computes ATR for the last N periods and returns their average.

        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of close prices
            atr_period: Period for ATR calculation (default: 14)
            average_period: Number of ATR values to average (default: 20)

        Returns:
            Average ATR value or None if insufficient data
        """
        required_data = average_period + atr_period + 1
        if len(high) < required_data or len(low) < required_data or len(close) < required_data:
            self.logger.warning(
                f"Not enough data for average ATR: need {required_data}, have {len(close)}"
            )
            return None

        try:
            atr_values = []

            # Calculate ATR for each of the last N periods
            for i in range(average_period):
                end_idx = len(high) - i
                start_idx = max(0, end_idx - atr_period - 1)

                if end_idx - start_idx >= atr_period + 1:
                    atr = self.calculate_atr(
                        high=high.iloc[start_idx:end_idx],
                        low=low.iloc[start_idx:end_idx],
                        close=close.iloc[start_idx:end_idx],
                        period=atr_period
                    )

                    if atr is not None:
                        atr_values.append(atr)

            if not atr_values:
                return None

            # Return average of all ATR values
            avg_atr = sum(atr_values) / len(atr_values)
            return float(avg_atr)

        except Exception as e:
            self.logger.error(f"Error calculating average ATR (legacy): {e}")
            return None
    
    def calculate_atr_ratio(
        self,
        current_atr: float,
        average_atr: float
    ) -> Optional[float]:
        """
        Calculate ratio of current ATR to average ATR.
        
        Args:
            current_atr: Current ATR value
            average_atr: Average ATR value
        
        Returns:
            ATR ratio or None if average is invalid
        """
        if average_atr <= 0:
            return None
        
        return current_atr / average_atr
    
    def is_atr_within_range(
        self,
        current_atr: float,
        average_atr: float,
        min_multiplier: float = 0.6,
        max_multiplier: float = 2.5
    ) -> bool:
        """
        Check if current ATR is within acceptable range of average ATR.
        
        Args:
            current_atr: Current ATR value
            average_atr: Average ATR value
            min_multiplier: Minimum acceptable ratio (default: 0.6)
            max_multiplier: Maximum acceptable ratio (default: 2.5)
        
        Returns:
            True if ATR is within range
        """
        ratio = self.calculate_atr_ratio(current_atr, average_atr)
        
        if ratio is None:
            return False
        
        return min_multiplier <= ratio <= max_multiplier

