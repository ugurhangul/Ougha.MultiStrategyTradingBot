"""
Candle-related data models.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CandleData:
    """OHLCV candle data"""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        return self.high - self.low


@dataclass
class ReferenceCandle:
    """
    Generic reference candle for range-based breakout detection.
    Can represent any timeframe (4H, 15M, etc.)
    """
    time: datetime
    high: float
    low: float
    open: float
    close: float
    timeframe: str  # e.g., "H4", "M15"
    is_processed: bool = False

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

