"""
Volume Analysis Service

Provides volume analysis and comparison utilities to eliminate duplication
in volume checking logic across TechnicalIndicators and strategy engines.
"""
import pandas as pd
from typing import Optional, TYPE_CHECKING
from enum import Enum
from src.constants import DEFAULT_VOLUME_PERIOD, MIN_DATA_POINTS_VOLUME

if TYPE_CHECKING:
    from src.utils.logger import TradingLogger

class VolumeCheckType(Enum):
    """Types of volume checks for different trading scenarios."""
    BREAKOUT_LOW = "Breakout Volume Check (Want LOW Volume)"
    REVERSAL_HIGH = "Reversal Volume Check (Want HIGH Volume)"
    TRUE_BREAKOUT_HIGH = "TRUE Breakout Volume Check (Want HIGH Volume)"
    CONTINUATION_HIGH = "Continuation Volume Check (Want HIGH Volume)"


class VolumeAnalysisService:
    """
    Service for volume analysis and comparison.
    
    This class provides methods to:
    - Calculate average volume over a period
    - Compare volume against thresholds
    - Check volume conditions for different trading scenarios
    - Provide consistent logging for volume analysis
    """
    
    def __init__(self, logger: 'TradingLogger'):
        """
        Initialize volume analysis service.

        Args:
            logger: Logger instance for logging volume analysis
        """
        self.logger = logger
    
    def calculate_average_volume(
        self,
        volumes: pd.Series,
        period: int = DEFAULT_VOLUME_PERIOD
    ) -> float:
        """
        Calculate average volume over a period.
        
        Args:
            volumes: Series of volume data
            period: Period for average (default from constants)
            
        Returns:
            Average volume, or 0.0 if insufficient data
        """
        if len(volumes) < period:
            self.logger.warning(
                f"Not enough data for volume average: {len(volumes)} < {period}"
            )
            return 0.0
        
        avg_volume = volumes.tail(period).mean()
        return float(avg_volume)
    
    def calculate_volume_ratio(
        self,
        current_volume: int,
        average_volume: float
    ) -> Optional[float]:
        """
        Calculate volume ratio (current / average).
        
        Args:
            current_volume: Current candle volume
            average_volume: Average volume
            
        Returns:
            Volume ratio, or None if average is invalid
        """
        if average_volume <= 0:
            return None
        
        return current_volume / average_volume
    
    def is_volume_low(
        self,
        current_volume: int,
        average_volume: float,
        max_threshold: float,
        symbol: str,
        check_type: VolumeCheckType = VolumeCheckType.BREAKOUT_LOW
    ) -> bool:
        """
        Check if volume is LOW (below or equal to threshold).
        
        Used for false breakout strategy where we want weak breakouts.
        
        Args:
            current_volume: Current candle volume
            average_volume: Average volume
            max_threshold: Maximum threshold multiplier (e.g., 1.5)
            symbol: Symbol name for logging
            check_type: Type of volume check for logging
            
        Returns:
            True if volume is low (ratio <= threshold), False otherwise
        """
        if average_volume <= 0:
            self.logger.warning("Average volume is zero or negative", symbol)
            return False
        
        volume_ratio = current_volume / average_volume
        is_low = volume_ratio <= max_threshold

        
        return is_low
    
    def is_volume_high(
        self,
        current_volume: int,
        average_volume: float,
        min_threshold: float,
        symbol: str,
        check_type: VolumeCheckType = VolumeCheckType.REVERSAL_HIGH
    ) -> bool:
        """
        Check if volume is HIGH (above or equal to threshold).
        
        Used for confirmations where we want strong volume.
        
        Args:
            current_volume: Current candle volume
            average_volume: Average volume
            min_threshold: Minimum threshold multiplier (e.g., 1.5)
            symbol: Symbol name for logging
            check_type: Type of volume check for logging
            
        Returns:
            True if volume is high (ratio >= threshold), False otherwise
        """
        if average_volume <= 0:
            self.logger.warning("Average volume is zero or negative", symbol)
            return False
        
        volume_ratio = current_volume / average_volume
        is_high = volume_ratio >= min_threshold

        
        return is_high

    

    
    def has_sufficient_data(self, volumes: pd.Series, period: int = DEFAULT_VOLUME_PERIOD) -> bool:
        """
        Check if there's sufficient volume data for analysis.
        
        Args:
            volumes: Series of volume data
            period: Required period
            
        Returns:
            True if sufficient data available, False otherwise
        """
        return len(volumes) >= MIN_DATA_POINTS_VOLUME or len(volumes) >= period + 1

