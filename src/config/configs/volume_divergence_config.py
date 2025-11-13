"""
Volume and divergence confirmation configuration.
"""
from dataclasses import dataclass


@dataclass
class VolumeConfig:
    """Volume confirmation settings"""
    breakout_volume_max_multiplier: float = 1.0
    reversal_volume_min_multiplier: float = 1.5
    volume_average_period: int = 20


@dataclass
class DivergenceConfig:
    """Divergence confirmation settings"""
    require_both_indicators: bool = False
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    divergence_lookback: int = 20

