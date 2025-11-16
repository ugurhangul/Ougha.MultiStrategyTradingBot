"""
Range configuration settings for multi-range breakout strategy.
"""
from dataclasses import dataclass, field
from datetime import time as dt_time
from typing import List
from src.models.data_models import RangeConfig


@dataclass
class RangeConfigSettings:
    """
    Range configuration settings for multi-range breakout strategy.

    Defines multiple independent range configurations that operate simultaneously.
    Each range has its own reference candle and breakout detection timeframe.
    """
    # Enable/disable multi-range mode
    enabled: bool = True

    # List of range configurations
    # Default: Two ranges operating simultaneously
    # - Range 1: 4H candle at 04:00 UTC (fallback: 00:00 UTC), 5M breakout detection, M5 ATR
    # - Range 2: 15M candle at 14:30 UTC (fallback: 14:00 UTC), 1M breakout detection, M1 ATR
    ranges: List[RangeConfig] = field(default_factory=lambda: [
        RangeConfig(
            range_id="4H_5M",
            reference_timeframe="H4",
            reference_time=dt_time(4, 0),  # 04:00 UTC
            fallback_reference_time=dt_time(12, 0),  # 00:00 UTC (fallback - previous 4H candle)
            breakout_timeframe="M5",
            use_specific_time=True,
            atr_timeframe="M5"  # M5 ATR for M5 scalping
        ),
        RangeConfig(
            range_id="15M_1M",
            reference_timeframe="M15",
            reference_time=dt_time(14, 30),  # 14:30 UTC (primary)
            fallback_reference_time=dt_time(15, 0),  # 14:00 UTC
            breakout_timeframe="M1",
            use_specific_time=True,
            atr_timeframe="M1"  # M1 ATR for M1 scalping
        )
    ])

