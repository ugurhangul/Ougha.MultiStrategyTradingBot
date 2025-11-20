"""
Real-time candle builder for tick-by-tick backtesting.

Builds OHLCV candles from tick data in real-time as ticks arrive.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional
import pandas as pd
from collections import defaultdict

from src.models.models.candle_models import CandleData
from src.utils.timeframe_converter import TimeframeConverter


class CandleBuilder:
    """
    Builds a single candle for a specific timeframe.
    
    Accumulates ticks and builds OHLCV data in real-time.
    """
    
    def __init__(self, timeframe: str, start_time: datetime):
        """
        Initialize candle builder.
        
        Args:
            timeframe: Timeframe string (M1, M5, M15, H1, H4)
            start_time: Start time of the candle (aligned to timeframe boundary)
        """
        self.timeframe = timeframe
        self.start_time = start_time
        self.duration_minutes = TimeframeConverter.get_duration_minutes(timeframe)
        
        # OHLCV data
        self.open: Optional[float] = None
        self.high: Optional[float] = None
        self.low: Optional[float] = None
        self.close: Optional[float] = None
        self.volume: int = 0
        
        # Track if candle is closed
        self.is_closed = False
    
    def add_tick(self, price: float, volume: int, tick_time: datetime) -> None:
        """
        Add a tick to the candle.
        
        Args:
            price: Tick price (use 'last' or 'bid' if last=0)
            volume: Tick volume
            tick_time: Tick timestamp
        """
        # First tick sets open
        if self.open is None:
            self.open = price
            self.high = price
            self.low = price
        
        # Update high/low
        if self.high is None or price > self.high:
            self.high = price
        if self.low is None or price < self.low:
            self.low = price
        
        # Every tick updates close
        self.close = price
        
        # Accumulate volume
        self.volume += volume
    
    def close_candle(self) -> None:
        """Mark candle as closed."""
        self.is_closed = True
    
    def to_candle_data(self) -> Optional[CandleData]:
        """
        Convert to CandleData object.
        
        Returns:
            CandleData or None if no ticks received
        """
        if self.open is None:
            return None
        
        return CandleData(
            time=self.start_time,
            open=self.open,
            high=self.high if self.high is not None else self.open,
            low=self.low if self.low is not None else self.open,
            close=self.close if self.close is not None else self.open,
            volume=self.volume
        )


class MultiTimeframeCandleBuilder:
    """
    Builds candles for multiple timeframes simultaneously from tick data.
    
    Maintains separate candle builders for M1, M5, M15, H1, H4 and manages
    candle boundaries (when to close current candle and start new one).
    """
    
    def __init__(self, symbol: str, timeframes: List[str]):
        """
        Initialize multi-timeframe candle builder.
        
        Args:
            symbol: Symbol name
            timeframes: List of timeframes to build (e.g., ['M1', 'M5', 'M15', 'H1', 'H4'])
        """
        self.symbol = symbol
        self.timeframes = timeframes
        
        # Current candle builders for each timeframe
        self.current_builders: Dict[str, Optional[CandleBuilder]] = {tf: None for tf in timeframes}
        
        # Completed candles for each timeframe (stored as list)
        self.completed_candles: Dict[str, List[CandleData]] = {tf: [] for tf in timeframes}
    
    def add_tick(self, price: float, volume: int, tick_time: datetime) -> None:
        """
        Add a tick to all timeframe builders.
        
        Automatically handles candle boundaries - closes current candle and
        starts new one when tick crosses timeframe boundary.
        
        Args:
            price: Tick price
            volume: Tick volume
            tick_time: Tick timestamp (must be timezone-aware UTC)
        """
        # Ensure tick_time is timezone-aware
        if tick_time.tzinfo is None:
            tick_time = tick_time.replace(tzinfo=timezone.utc)
        
        for timeframe in self.timeframes:
            # Get candle start time for this tick (aligned to timeframe boundary)
            candle_start = self._align_to_timeframe(tick_time, timeframe)
            
            # Check if we need to start a new candle
            current_builder = self.current_builders[timeframe]

            if current_builder is None or current_builder.start_time != candle_start:
                # Close previous candle if exists
                if current_builder is not None and not current_builder.is_closed:
                    current_builder.close_candle()
                    candle_data = current_builder.to_candle_data()
                    if candle_data is not None:
                        self.completed_candles[timeframe].append(candle_data)

                # Start new candle
                self.current_builders[timeframe] = CandleBuilder(timeframe, candle_start)
                current_builder = self.current_builders[timeframe]

            # Add tick to current candle
            current_builder.add_tick(price, volume, tick_time)

    def get_candles(self, timeframe: str, count: int = 100) -> Optional[pd.DataFrame]:
        """
        Get completed candles for a timeframe.

        Returns the last N **closed** candles. The current (incomplete) candle
        is NOT included.

        Args:
            timeframe: Timeframe string
            count: Number of candles to return

        Returns:
            DataFrame with OHLCV data or None if no candles
        """
        if timeframe not in self.completed_candles:
            return None

        candles = self.completed_candles[timeframe]
        if len(candles) == 0:
            return None

        # Get last N candles
        candles_to_return = candles[-count:] if len(candles) > count else candles

        # Convert to DataFrame
        data = {
            'time': [c.time for c in candles_to_return],
            'open': [c.open for c in candles_to_return],
            'high': [c.high for c in candles_to_return],
            'low': [c.low for c in candles_to_return],
            'close': [c.close for c in candles_to_return],
            'tick_volume': [c.volume for c in candles_to_return],
        }

        return pd.DataFrame(data)

    def get_latest_candle(self, timeframe: str) -> Optional[CandleData]:
        """
        Get the latest **closed** candle for a timeframe.

        Returns:
            CandleData or None if no closed candles
        """
        if timeframe not in self.completed_candles:
            return None

        candles = self.completed_candles[timeframe]
        if len(candles) == 0:
            return None

        return candles[-1]

    def get_current_candle(self, timeframe: str) -> Optional[CandleData]:
        """
        Get the current (incomplete) candle for a timeframe.

        This is useful for intra-bar analysis (e.g., checking if price
        touched SL/TP during the current candle).

        Returns:
            CandleData or None if no current candle
        """
        if timeframe not in self.current_builders:
            return None

        builder = self.current_builders[timeframe]
        if builder is None:
            return None

        return builder.to_candle_data()

    def seed_historical_candles(self, timeframe: str, candles_df: pd.DataFrame) -> None:
        """
        Pre-seed the candle builder with historical OHLC data.

        This allows strategies to have sufficient candle history from the start
        of the backtest, before any ticks are processed.

        Args:
            timeframe: Timeframe string (M1, M5, M15, H1, H4)
            candles_df: DataFrame with columns: time, open, high, low, close, tick_volume
        """
        if timeframe not in self.completed_candles:
            return

        if candles_df is None or len(candles_df) == 0:
            return

        # Convert DataFrame rows to CandleData objects
        for _, row in candles_df.iterrows():
            candle = CandleData(
                time=row['time'],
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                volume=int(row.get('tick_volume', 0))
            )
            self.completed_candles[timeframe].append(candle)

    def _align_to_timeframe(self, dt: datetime, timeframe: str) -> datetime:
        """
        Align datetime to timeframe boundary.

        Examples:
            M1: 2025-11-14 10:23:45 -> 2025-11-14 10:23:00
            M5: 2025-11-14 10:23:45 -> 2025-11-14 10:20:00
            M15: 2025-11-14 10:23:45 -> 2025-11-14 10:15:00
            H1: 2025-11-14 10:23:45 -> 2025-11-14 10:00:00
            H4: 2025-11-14 10:23:45 -> 2025-11-14 08:00:00

        Args:
            dt: Datetime to align
            timeframe: Timeframe string

        Returns:
            Aligned datetime
        """
        duration_minutes = TimeframeConverter.get_duration_minutes(timeframe)
        if duration_minutes is None:
            return dt

        # Calculate total minutes since midnight
        total_minutes = dt.hour * 60 + dt.minute

        # Round down to nearest timeframe boundary
        aligned_minutes = (total_minutes // duration_minutes) * duration_minutes

        # Reconstruct datetime
        aligned_hour = aligned_minutes // 60
        aligned_minute = aligned_minutes % 60

        return dt.replace(hour=aligned_hour, minute=aligned_minute, second=0, microsecond=0)

