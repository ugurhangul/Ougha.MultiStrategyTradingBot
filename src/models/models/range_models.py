"""
Range configuration models.
"""
from dataclasses import dataclass
from datetime import time
from typing import Optional


@dataclass
class RangeConfig:
    """
    Configuration for a single range-based breakout strategy.

    Defines:
    - Reference candle: The candle that establishes the high/low range
    - Breakout candle: The smaller timeframe candle used to detect breakouts

    Examples:
    - Range 1: 4H candle at 04:00 UTC, 5M breakout detection, M5 ATR
    - Range 2: 15M candle at 04:30 UTC, 1M breakout detection, M1 ATR
    """
    # Unique identifier for this range configuration
    range_id: str

    # Reference candle configuration (establishes the range)
    reference_timeframe: str  # e.g., "H4", "M15"

    # Breakout detection candle configuration
    breakout_timeframe: str  # e.g., "M5", "M1"

    # Optional fields with defaults
    reference_time: Optional[time] = None  # Specific time to use (e.g., 04:00 for 4H, 04:30 for 15M)
    fallback_reference_time: Optional[time] = None  # Specific time to use (e.g., 04:00 for 4H, 04:30 for 15M)
    use_specific_time: bool = True  # Whether to use only specific reference candle times

    # ATR configuration for this range
    atr_timeframe: Optional[str] = None  # ATR timeframe (e.g., "M5", "M1") - defaults to breakout_timeframe if None

    def __str__(self) -> str:
        """String representation for logging"""
        if self.use_specific_time and self.reference_time:
            return f"{self.range_id} ({self.reference_timeframe}@{self.reference_time.strftime('%H:%M')} -> {self.breakout_timeframe})"
        return f"{self.range_id} ({self.reference_timeframe} -> {self.breakout_timeframe})"

