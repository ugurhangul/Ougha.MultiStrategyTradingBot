"""
Swing Point Indicator

Detects swing highs and swing lows in price data.
A swing point is a local extremum where the price is higher/lower than surrounding prices.

Used for divergence detection and pattern analysis.
"""
import numpy as np
from typing import Optional, List, Tuple
from src.utils.logger import get_logger


class SwingPointIndicator:
    """
    Swing point detection indicator.
    
    Identifies local peaks (swing highs) and troughs (swing lows) in price data.
    A swing high is a price point that is higher than the prices immediately before and after it.
    A swing low is a price point that is lower than the prices immediately before and after it.
    """
    
    def __init__(self):
        """Initialize swing point indicator."""
        self.logger = get_logger()
    
    def find_swing_low(
        self,
        lows: np.ndarray,
        lookback: int = 20,
        exclude_last: int = 2
    ) -> Optional[int]:
        """
        Find the most recent swing low in price data.
        
        A swing low is identified when:
        - lows[i] < lows[i-1] AND lows[i] < lows[i+1]
        
        Args:
            lows: Array of low prices
            lookback: Maximum number of candles to look back
            exclude_last: Number of most recent candles to exclude (default: 2 to exclude current candle)
        
        Returns:
            Index of swing low, or None if not found
        """
        if len(lows) < exclude_last + 3:
            return None
        
        # Search backwards from (len - exclude_last - 1) to (len - lookback - 1)
        start_idx = len(lows) - exclude_last - 1
        end_idx = max(0, len(lows) - lookback - 1)
        
        for i in range(start_idx, end_idx, -1):
            # Need at least one candle on each side
            if i > 0 and i < len(lows) - 1:
                # Check if this is a swing low
                if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                    return i
        
        return None
    
    def find_swing_high(
        self,
        highs: np.ndarray,
        lookback: int = 20,
        exclude_last: int = 2
    ) -> Optional[int]:
        """
        Find the most recent swing high in price data.
        
        A swing high is identified when:
        - highs[i] > highs[i-1] AND highs[i] > highs[i+1]
        
        Args:
            highs: Array of high prices
            lookback: Maximum number of candles to look back
            exclude_last: Number of most recent candles to exclude (default: 2 to exclude current candle)
        
        Returns:
            Index of swing high, or None if not found
        """
        if len(highs) < exclude_last + 3:
            return None
        
        # Search backwards from (len - exclude_last - 1) to (len - lookback - 1)
        start_idx = len(highs) - exclude_last - 1
        end_idx = max(0, len(highs) - lookback - 1)
        
        for i in range(start_idx, end_idx, -1):
            # Need at least one candle on each side
            if i > 0 and i < len(highs) - 1:
                # Check if this is a swing high
                if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                    return i
        
        return None
    
    def find_all_swing_lows(
        self,
        lows: np.ndarray,
        lookback: int = 20,
        exclude_last: int = 2
    ) -> List[int]:
        """
        Find all swing lows in the lookback period.
        
        Args:
            lows: Array of low prices
            lookback: Maximum number of candles to look back
            exclude_last: Number of most recent candles to exclude
        
        Returns:
            List of indices where swing lows occur
        """
        swing_lows = []
        
        if len(lows) < exclude_last + 3:
            return swing_lows
        
        start_idx = len(lows) - exclude_last - 1
        end_idx = max(0, len(lows) - lookback - 1)
        
        for i in range(start_idx, end_idx, -1):
            if i > 0 and i < len(lows) - 1:
                if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                    swing_lows.append(i)
        
        return swing_lows
    
    def find_all_swing_highs(
        self,
        highs: np.ndarray,
        lookback: int = 20,
        exclude_last: int = 2
    ) -> List[int]:
        """
        Find all swing highs in the lookback period.
        
        Args:
            highs: Array of high prices
            lookback: Maximum number of candles to look back
            exclude_last: Number of most recent candles to exclude
        
        Returns:
            List of indices where swing highs occur
        """
        swing_highs = []
        
        if len(highs) < exclude_last + 3:
            return swing_highs
        
        start_idx = len(highs) - exclude_last - 1
        end_idx = max(0, len(highs) - lookback - 1)
        
        for i in range(start_idx, end_idx, -1):
            if i > 0 and i < len(highs) - 1:
                if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                    swing_highs.append(i)
        
        return swing_highs

