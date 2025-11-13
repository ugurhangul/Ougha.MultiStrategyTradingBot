"""
Price Range Indicator

Calculates price ranges and range-based metrics.
Used for range detection, breakout analysis, and volatility assessment.
"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from datetime import datetime
from src.utils.logger import get_logger


class PriceRangeIndicator:
    """
    Price range calculation indicator.
    
    Provides utilities for:
    - Candle range calculation (high - low)
    - Range statistics over multiple candles
    - Range-based volatility measures
    """
    
    def __init__(self):
        """Initialize price range indicator."""
        self.logger = get_logger()
    
    def calculate_candle_range(
        self,
        high: float,
        low: float
    ) -> float:
        """
        Calculate range of a single candle.
        
        Args:
            high: Candle high price
            low: Candle low price
        
        Returns:
            Range size (high - low)
        """
        return high - low
    
    def calculate_range_points(
        self,
        high: float,
        low: float,
        point: float
    ) -> float:
        """
        Calculate range in points.
        
        Args:
            high: Candle high price
            low: Candle low price
            point: Symbol point size
        
        Returns:
            Range size in points
        """
        if point <= 0:
            return 0.0
        
        range_price = high - low
        range_points = range_price / point
        
        return range_points
    
    def calculate_average_range(
        self,
        highs: pd.Series,
        lows: pd.Series,
        period: int = 20
    ) -> Optional[float]:
        """
        Calculate average range over multiple candles.
        
        Args:
            highs: Series of high prices
            lows: Series of low prices
            period: Number of candles to average
        
        Returns:
            Average range or None if insufficient data
        """
        if len(highs) < period or len(lows) < period:
            return None
        
        # Calculate range for each candle
        ranges = highs.tail(period) - lows.tail(period)
        
        # Return average
        return float(ranges.mean())
    
    def detect_range_from_candle(
        self,
        high: float,
        low: float,
        candle_time: datetime
    ) -> Dict[str, Any]:
        """
        Detect and package range information from a candle.
        
        Args:
            high: Candle high price
            low: Candle low price
            candle_time: Candle timestamp
        
        Returns:
            Dictionary with range information
        """
        range_size = self.calculate_candle_range(high, low)
        
        return {
            'high': high,
            'low': low,
            'range': range_size,
            'time': candle_time
        }
    
    def calculate_range_percentage(
        self,
        high: float,
        low: float,
        reference_price: float
    ) -> float:
        """
        Calculate range as percentage of reference price.
        
        Args:
            high: Range high
            low: Range low
            reference_price: Reference price (e.g., close, mid-price)
        
        Returns:
            Range as percentage
        """
        if reference_price <= 0:
            return 0.0
        
        range_size = high - low
        range_pct = (range_size / reference_price) * 100
        
        return range_pct
    
    def is_range_within_bounds(
        self,
        current_range: float,
        min_range: float,
        max_range: float
    ) -> bool:
        """
        Check if range is within acceptable bounds.
        
        Args:
            current_range: Current range size
            min_range: Minimum acceptable range
            max_range: Maximum acceptable range
        
        Returns:
            True if range is within bounds
        """
        return min_range <= current_range <= max_range
    
    def calculate_range_statistics(
        self,
        highs: pd.Series,
        lows: pd.Series,
        period: int = 20
    ) -> Dict[str, float]:
        """
        Calculate comprehensive range statistics.
        
        Args:
            highs: Series of high prices
            lows: Series of low prices
            period: Number of candles to analyze
        
        Returns:
            Dictionary with range statistics
        """
        if len(highs) < period or len(lows) < period:
            return {}
        
        # Calculate ranges for each candle
        ranges = highs.tail(period) - lows.tail(period)
        
        return {
            'current': float(ranges.iloc[-1]),
            'average': float(ranges.mean()),
            'min': float(ranges.min()),
            'max': float(ranges.max()),
            'std': float(ranges.std())
        }

