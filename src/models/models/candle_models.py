"""
Candle-related data models.
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CandleData:
    """
    OHLCV candle data.

    PERFORMANCE OPTIMIZATION #7: Uses __slots__ to reduce memory overhead
    and improve attribute access speed. Candles are created frequently during
    backtesting, so this optimization provides significant memory savings.
    """
    __slots__ = ('time', 'open', 'high', 'low', 'close', 'volume')

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


class ReferenceCandle:
    """
    Generic reference candle for range-based breakout detection.
    Can represent any timeframe (4H, 15M, etc.)

    PERFORMANCE OPTIMIZATION #7: Uses __slots__ to reduce memory overhead.
    Note: Not using @dataclass to avoid conflicts with __slots__ and default values.
    """
    __slots__ = ('time', 'high', 'low', 'open', 'close', 'timeframe', 'is_processed')

    def __init__(self, time: datetime, high: float, low: float, open: float, close: float,
                 timeframe: str, is_processed: bool = False):
        self.time = time
        self.high = high
        self.low = low
        self.open = open
        self.close = close
        self.timeframe = timeframe
        self.is_processed = is_processed

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

