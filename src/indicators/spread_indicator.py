"""
Spread Indicator

Calculates and analyzes bid-ask spreads for trading instruments.
Used for spread filtering and market condition assessment.
"""
from typing import List, Optional, NamedTuple
from src.utils.logger import get_logger


class TickData(NamedTuple):
    """Tick data structure"""
    bid: float
    ask: float
    volume: int
    time: float


class SpreadIndicator:
    """
    Spread calculation and analysis indicator.
    
    Calculates bid-ask spreads and provides utilities for:
    - Current spread calculation
    - Average spread over lookback period
    - Spread filtering based on thresholds
    """
    
    def __init__(self):
        """Initialize spread indicator."""
        self.logger = get_logger()
    
    def calculate_spread_points(
        self,
        bid: float,
        ask: float,
        point: float
    ) -> float:
        """
        Calculate spread in points.
        
        Args:
            bid: Bid price
            ask: Ask price
            point: Symbol point size
        
        Returns:
            Spread in points
        """
        if point <= 0:
            return 0.0
        
        spread_price = ask - bid
        spread_points = spread_price / point
        
        return spread_points
    
    def calculate_average_spread_from_ticks(
        self,
        ticks: List[TickData],
        point: float,
        lookback: Optional[int] = None
    ) -> Optional[float]:
        """
        Calculate average spread from tick data.
        
        Args:
            ticks: List of tick data
            point: Symbol point size
            lookback: Number of recent ticks to use (None = use all)
        
        Returns:
            Average spread in points or None if insufficient data
        """
        if not ticks or point <= 0:
            return None
        
        # Use last N ticks if lookback specified
        if lookback is not None and lookback > 0:
            recent_ticks = ticks[-lookback:]
        else:
            recent_ticks = ticks
        
        if not recent_ticks:
            return None
        
        # Calculate spread for each tick
        spreads = [tick.ask - tick.bid for tick in recent_ticks]
        
        # Calculate average spread in price units
        avg_spread_price = sum(spreads) / len(spreads)
        
        # Convert to points
        avg_spread_points = avg_spread_price / point
        
        return avg_spread_points
    
    def calculate_spread_ratio(
        self,
        current_spread: float,
        average_spread: float
    ) -> Optional[float]:
        """
        Calculate ratio of current spread to average spread.
        
        Args:
            current_spread: Current spread in points
            average_spread: Average spread in points
        
        Returns:
            Spread ratio or None if average is invalid
        """
        if average_spread <= 0:
            return None
        
        return current_spread / average_spread
    
    def is_spread_acceptable(
        self,
        current_spread: float,
        average_spread: float,
        max_multiplier: float = 2.0
    ) -> bool:
        """
        Check if current spread is acceptable.
        
        Args:
            current_spread: Current spread in points
            average_spread: Average spread in points
            max_multiplier: Maximum acceptable spread multiplier
        
        Returns:
            True if spread is acceptable
        """
        if average_spread <= 0:
            return True  # Skip check if no average available
        
        ratio = self.calculate_spread_ratio(current_spread, average_spread)
        
        if ratio is None:
            return True
        
        return ratio <= max_multiplier
    
    def is_spread_below_threshold(
        self,
        current_spread: float,
        max_spread_points: float
    ) -> bool:
        """
        Check if spread is below absolute threshold.
        
        Args:
            current_spread: Current spread in points
            max_spread_points: Maximum acceptable spread in points
        
        Returns:
            True if spread is below threshold
        """
        return current_spread <= max_spread_points
    
    def calculate_spread_statistics(
        self,
        ticks: List[TickData],
        point: float
    ) -> dict:
        """
        Calculate comprehensive spread statistics.
        
        Args:
            ticks: List of tick data
            point: Symbol point size
        
        Returns:
            Dictionary with spread statistics
        """
        if not ticks or point <= 0:
            return {}
        
        spreads = [(tick.ask - tick.bid) / point for tick in ticks]
        
        return {
            'current': spreads[-1] if spreads else 0.0,
            'average': sum(spreads) / len(spreads) if spreads else 0.0,
            'min': min(spreads) if spreads else 0.0,
            'max': max(spreads) if spreads else 0.0,
            'count': len(spreads)
        }

