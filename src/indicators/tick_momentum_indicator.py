"""
Tick Momentum Indicator

Calculates tick-level momentum by analyzing consecutive tick movements.
Used for high-frequency trading strategies to detect rapid price movements.
"""
from typing import List, NamedTuple, Optional
from src.utils.logger import get_logger


class TickData(NamedTuple):
    """Tick data structure"""
    bid: float
    ask: float
    volume: int
    time: float


class TickMomentumIndicator:
    """
    Tick-level momentum indicator.
    
    Detects momentum by analyzing consecutive tick movements:
    - Upward momentum: All bids rising consecutively
    - Downward momentum: All asks falling consecutively
    - Cumulative movement: Sum of tick-to-tick price changes
    """
    
    def __init__(self):
        """Initialize tick momentum indicator."""
        self.logger = get_logger()
    
    def detect_consecutive_upward_movement(
        self,
        ticks: List[TickData],
        min_count: int = 2
    ) -> bool:
        """
        Detect consecutive upward tick movement.
        
        Checks if all bids are rising consecutively.
        
        Args:
            ticks: List of tick data
            min_count: Minimum number of consecutive ticks required
        
        Returns:
            True if upward momentum detected
        """
        if len(ticks) < min_count:
            return False
        
        for i in range(1, len(ticks)):
            if ticks[i].bid <= ticks[i-1].bid:
                return False
        
        return True
    
    def detect_consecutive_downward_movement(
        self,
        ticks: List[TickData],
        min_count: int = 2
    ) -> bool:
        """
        Detect consecutive downward tick movement.
        
        Checks if all asks are falling consecutively.
        
        Args:
            ticks: List of tick data
            min_count: Minimum number of consecutive ticks required
        
        Returns:
            True if downward momentum detected
        """
        if len(ticks) < min_count:
            return False
        
        for i in range(1, len(ticks)):
            if ticks[i].ask >= ticks[i-1].ask:
                return False
        
        return True
    
    def calculate_cumulative_upward_movement(
        self,
        ticks: List[TickData]
    ) -> float:
        """
        Calculate cumulative upward price movement.
        
        Sums all positive tick-to-tick bid changes.
        
        Args:
            ticks: List of tick data
        
        Returns:
            Cumulative upward movement in price units
        """
        if len(ticks) < 2:
            return 0.0
        
        cumulative = 0.0
        for i in range(1, len(ticks)):
            tick_change = ticks[i].bid - ticks[i-1].bid
            if tick_change > 0:
                cumulative += tick_change
        
        return cumulative
    
    def calculate_cumulative_downward_movement(
        self,
        ticks: List[TickData]
    ) -> float:
        """
        Calculate cumulative downward price movement.
        
        Sums all positive tick-to-tick ask changes (falling prices).
        
        Args:
            ticks: List of tick data
        
        Returns:
            Cumulative downward movement in price units
        """
        if len(ticks) < 2:
            return 0.0
        
        cumulative = 0.0
        for i in range(1, len(ticks)):
            tick_change = ticks[i-1].ask - ticks[i].ask
            if tick_change > 0:
                cumulative += tick_change
        
        return cumulative
    
    def check_momentum_strength(
        self,
        ticks: List[TickData],
        direction: int,
        min_strength: float
    ) -> bool:
        """
        Check if momentum strength exceeds minimum threshold.
        
        Args:
            ticks: List of tick data
            direction: 1 for BUY (upward), -1 for SELL (downward)
            min_strength: Minimum cumulative movement required
        
        Returns:
            True if momentum strength exceeds threshold
        """
        if direction > 0:
            movement = self.calculate_cumulative_upward_movement(ticks)
        else:
            movement = self.calculate_cumulative_downward_movement(ticks)
        
        return movement >= min_strength

