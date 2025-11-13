"""
Pattern-Based Position Sizer

Position sizing strategy that also calculates stop loss based on pattern highs/lows.
This sizer analyzes the reference candle pattern to determine optimal stop loss placement.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass

from src.risk.position_sizing.base_position_sizer import BasePositionSizer
from src.risk.position_sizing.position_sizer_factory import register_position_sizer
from src.core.mt5_connector import MT5Connector
from src.models.data_models import ReferenceCandle, CandleData, PositionType
from src.utils.logger import get_logger


@dataclass
class StopLossResult:
    """Result of stop loss calculation"""
    stop_loss: float
    pattern_high: float
    pattern_low: float
    spread_applied: float


@register_position_sizer(
    "pattern_based",
    description="Pattern-based position sizing with spread-based SL calculation from execution timeframe extremes",
    default=False
)
class PatternBasedPositionSizer(BasePositionSizer):
    """
    Pattern-based position sizing strategy.

    This position sizer extends the standard fixed lot sizing with the ability
    to calculate stop loss levels based on recent price action on the execution timeframe.

    Features:
    - Fixed lot size based on risk percentage
    - Stop loss calculation using highest high / lowest low from last 10 candles on execution timeframe
    - Dynamic execution timeframe based on strategy configuration (e.g., M1, M5)
    - Spread-based buffer (uses current spread as natural buffer between BID/ASK)
    - Graceful handling of limited candle availability
    """

    def __init__(self, symbol: str, connector: MT5Connector,
                 execution_timeframe: str = 'M1',
                 **kwargs):
        """
        Initialize pattern-based position sizer.

        Args:
            symbol: Trading symbol
            connector: MT5 connector for symbol info and spread retrieval
            execution_timeframe: Execution timeframe for stop loss calculation (e.g., 'M1', 'M5')
            **kwargs: Additional parameters
        """
        super().__init__(symbol, **kwargs)
        self.logger = get_logger()
        self.connector = connector
        self.execution_timeframe = execution_timeframe

        # Lot sizing state
        self.initial_lot_size: float = 0.0
        self.current_lot_size: float = 0.0

        # Statistics
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
    
    def initialize(self, initial_lot_size: float) -> bool:
        """
        Initialize with base lot size.

        Args:
            initial_lot_size: Base lot size from risk manager

        Returns:
            True if successful
        """
        self.initial_lot_size = initial_lot_size
        self.current_lot_size = initial_lot_size
        self.is_initialized = True

        self.logger.info(
            f"Pattern-based position sizer initialized for {self.symbol}: "
            f"{initial_lot_size:.2f} lots (Spread-based SL, Execution TF: {self.execution_timeframe})",
            self.symbol
        )

        return True
    
    def calculate_lot_size(self) -> float:
        """
        Calculate lot size (returns fixed size).
        
        Returns:
            Fixed lot size
        """
        return self.current_lot_size
    
    def on_trade_closed(self, profit: float, lot_size: float) -> None:
        """
        Update statistics after trade closure.
        
        Args:
            profit: Trade profit/loss
            lot_size: Lot size of closed trade
        """
        self.total_trades += 1
        
        if profit > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        self.logger.debug(
            f"Trade closed: {'WIN' if profit > 0 else 'LOSS'} ${profit:.2f} | "
            f"Lot size remains: {self.current_lot_size:.2f}",
            self.symbol
        )
    
    def reset(self) -> None:
        """
        Reset to initial state.
        """
        self.current_lot_size = self.initial_lot_size
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        self.logger.info(f"Pattern-based position sizer reset for {self.symbol}", self.symbol)
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get current state.

        Returns:
            State dictionary
        """
        return {
            'type': 'pattern_based',
            'symbol': self.symbol,
            'is_initialized': self.is_initialized,
            'initial_lot_size': self.initial_lot_size,
            'current_lot_size': self.current_lot_size,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0,
            'config': {
                'execution_timeframe': self.execution_timeframe,
                'sl_method': 'spread_based'
            }
        }

    def is_enabled(self) -> bool:
        """
        Check if position sizer is enabled.

        Returns:
            Always True for pattern-based sizing
        """
        return self.is_initialized

    # ========== STOP LOSS CALCULATION METHODS ==========

    def calculate_pattern_extremes(self, reference_candle: ReferenceCandle,
                                   breakout_candles: Optional[list] = None) -> tuple:
        """
        Calculate the highest high and lowest low from the pattern.

        The pattern consists of:
        - The reference candle (e.g., 4H or 15M candle)
        - Optional breakout candles (candles that formed during breakout)

        Args:
            reference_candle: The reference candle
            breakout_candles: Optional list of CandleData objects from breakout phase

        Returns:
            Tuple of (highest_high, lowest_low)
        """
        # Start with reference candle extremes
        highest_high = reference_candle.high
        lowest_low = reference_candle.low

        # Include breakout candles if provided
        if breakout_candles:
            for candle in breakout_candles:
                if candle.high > highest_high:
                    highest_high = candle.high
                if candle.low < lowest_low:
                    lowest_low = candle.low

        return highest_high, lowest_low

    def _get_execution_timeframe_extremes(self, candle_count: int = 10) -> tuple:
        """
        Calculate the highest high and lowest low from recent execution timeframe candles.

        Retrieves the most recent closed candles from the configured execution timeframe
        and calculates their extremes for stop loss placement.

        Args:
            candle_count: Number of recent candles to analyze (default: 10)

        Returns:
            Tuple of (highest_high, lowest_low)

        Raises:
            ValueError: If unable to retrieve candle data
        """
        # Retrieve last N+1 candles from execution timeframe (we need N closed candles)
        df = self.connector.get_candles(self.symbol, self.execution_timeframe, count=candle_count + 1)

        if df is None or len(df) < 2:
            raise ValueError(
                f"Failed to retrieve {self.execution_timeframe} candles for {self.symbol}. "
                f"Cannot calculate stop loss based on execution timeframe."
            )

        # Use only closed candles (exclude the current forming candle)
        closed_candles = df.iloc[:-1]

        # Handle case where fewer candles are available than requested
        actual_count = len(closed_candles)
        if actual_count < candle_count:
            self.logger.warning(
                f"Only {actual_count} closed {self.execution_timeframe} candles available for {self.symbol}, "
                f"requested {candle_count}. Using available candles for SL calculation.",
                self.symbol
            )

        # Calculate extremes from the closed candles
        highest_high = closed_candles['high'].max()
        lowest_low = closed_candles['low'].min()

        self.logger.debug(
            f"Calculated {self.execution_timeframe} extremes from {actual_count} candles: "
            f"High={highest_high:.5f}, Low={lowest_low:.5f}",
            self.symbol
        )

        return highest_high, lowest_low

    def calculate_stop_loss_for_buy(self, reference_candle: ReferenceCandle,
                                    breakout_candles: Optional[list] = None) -> StopLossResult:
        """
        Calculate stop loss for BUY signal using spread-based approach.

        For BUY signals, stop loss is placed below the lowest low of the last 10 candles
        on the configured execution timeframe (e.g., M1 for 15M_1M range, M5 for 4H_5M range),
        minus the spread.

        The spread adjustment is needed because:
        - Pattern low is based on BID prices (candle lows)
        - Entry is at ASK price (BID + spread)
        - SL triggers when BID reaches SL level
        - Subtracting spread ensures proper distance from pattern low

        Args:
            reference_candle: The reference candle (not used in current implementation)
            breakout_candles: Optional list of breakout candles (not used in current implementation)

        Returns:
            StopLossResult with calculated stop loss and pattern data

        Raises:
            ValueError: If unable to retrieve symbol info or candle data
        """
        # Get symbol info
        symbol_info = self.connector.get_symbol_info(self.symbol)
        if symbol_info is None:
            raise ValueError(f"Failed to get symbol info for {self.symbol}")

        digits = symbol_info['digits']
        point = symbol_info['point']

        # Get current spread
        spread_points = self.connector.get_spread(self.symbol)
        if spread_points is None:
            raise ValueError(f"Failed to get spread for {self.symbol}")

        spread_price = spread_points * point

        # Calculate extremes from last 10 candles on execution timeframe
        pattern_high, pattern_low = self._get_execution_timeframe_extremes(candle_count=10)

        # For BUY: SL = pattern_low - spread
        stop_loss = pattern_low - spread_price
        stop_loss = round(stop_loss, digits)

        self.logger.debug(
            f"BUY SL calculated from 10x{self.execution_timeframe} candles: SL={stop_loss:.5f}, "
            f"Pattern Low={pattern_low:.5f}, Spread={spread_price:.5f}",
            self.symbol
        )

        return StopLossResult(
            stop_loss=stop_loss,
            pattern_high=pattern_high,
            pattern_low=pattern_low,
            spread_applied=spread_price
        )

    def calculate_stop_loss_for_sell(self, reference_candle: ReferenceCandle,
                                     breakout_candles: Optional[list] = None) -> StopLossResult:
        """
        Calculate stop loss for SELL signal using spread-based approach.

        For SELL signals, stop loss is placed above the highest high of the last 10 candles
        on the configured execution timeframe (e.g., M1 for 15M_1M range, M5 for 4H_5M range),
        plus the spread.

        The spread adjustment is needed because:
        - Pattern high is based on ASK prices (candle highs)
        - Entry is at BID price
        - SL triggers when ASK reaches SL level
        - Need to add spread to account for BID/ASK difference

        Args:
            reference_candle: The reference candle (not used in current implementation)
            breakout_candles: Optional list of breakout candles (not used in current implementation)

        Returns:
            StopLossResult with calculated stop loss and pattern data

        Raises:
            ValueError: If unable to retrieve symbol info or candle data
        """
        # Get symbol info
        symbol_info = self.connector.get_symbol_info(self.symbol)
        if symbol_info is None:
            raise ValueError(f"Failed to get symbol info for {self.symbol}")

        digits = symbol_info['digits']
        point = symbol_info['point']

        # Get current spread
        spread_points = self.connector.get_spread(self.symbol)
        if spread_points is None:
            raise ValueError(f"Failed to get spread for {self.symbol}")

        spread_price = spread_points * point

        # Calculate extremes from last 10 candles on execution timeframe
        pattern_high, pattern_low = self._get_execution_timeframe_extremes(candle_count=10)

        # For SELL: SL = pattern_high + spread (to account for BID/ASK difference)
        stop_loss = pattern_high + spread_price
        stop_loss = round(stop_loss, digits)

        self.logger.debug(
            f"SELL SL calculated from 10x{self.execution_timeframe} candles: SL={stop_loss:.5f}, "
            f"Pattern High={pattern_high:.5f}, Spread={spread_price:.5f}",
            self.symbol
        )

        return StopLossResult(
            stop_loss=stop_loss,
            pattern_high=pattern_high,
            pattern_low=pattern_low,
            spread_applied=spread_price
        )

