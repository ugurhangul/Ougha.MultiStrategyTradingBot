"""
True Breakout Strategy - Continuation after retest confirmation.

Implements a breakout strategy that requires:
1. Valid breakout (candle open INSIDE range, close OUTSIDE range)
2. High volume on breakout
3. Retest of breakout level
4. Continuation in breakout direction with volume confirmation

Supports multiple range configurations (4H_5M, 15M_1M) operating independently.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import pandas as pd

from src.strategy.base_strategy import BaseStrategy, ValidationResult
from src.strategy.strategy_factory import register_strategy
from src.strategy.validation_decorator import validation_check, auto_register_validations
from src.strategy.adaptive_filter import AdaptiveFilter
from src.models.data_models import (
    TradeSignal, PositionType, SymbolCategory, SymbolParameters, CandleData, ReferenceCandle,
    UnifiedBreakoutState
)
from src.core.mt5_connector import MT5Connector
from src.execution.order_manager import OrderManager
from src.execution.trade_manager import TradeManager
from src.risk.risk_manager import RiskManager
from src.risk.position_sizing.pattern_based_position_sizer import PatternBasedPositionSizer
from src.indicators.technical_indicators import TechnicalIndicators
from src.config.strategies import TrueBreakoutConfig
from src.config.symbols import SymbolParametersRepository
from src.config.trading_config import TradingConfig
from src.utils.strategy import (
    SymbolCategoryUtils, StopLossCalculator, ValidationThresholdsCalculator,
    SignalValidationHelpers, RangeDetector, BreakoutDetector, ContinuationValidator
)
from src.utils.logger import get_logger
from src.utils.timeframe_converter import TimeframeConverter
from src.utils.volume_cache import VolumeCache  # OPTIMIZATION #5: Phase 2
from src.constants import RETEST_RANGE_PERCENT

# Constants
DEFAULT_INITIALIZATION_SL_POINTS = 100  # Default stop loss points for position sizer initialization


@register_strategy(
    "true_breakout",
    description="True breakout strategy with retest confirmation",
    enabled_by_default=True,
    requires_tick_data=False
)
class TrueBreakoutStrategy(BaseStrategy):
    """
    True Breakout Strategy - Continuation after retest.

    Strategy Logic:
    1. Detect valid breakout (open INSIDE range, close OUTSIDE)
    2. Verify high volume on breakout candle
    3. Wait for retest of breakout level
    4. Confirm continuation with volume
    5. Enter trade with stop loss below/above pattern low/high

    Thread Safety:
    This strategy is NOT thread-safe. Each instance should only be called from a single thread.
    The current architecture ensures this by having one strategy instance per symbol, with each
    symbol processed in its own thread or sequentially by the orchestrator.
    """
    
    def __init__(self, symbol: str, connector: MT5Connector,
                 order_manager: OrderManager, risk_manager: RiskManager,
                 trade_manager: TradeManager, indicators: TechnicalIndicators,
                 position_sizer=None,
                 config: Optional[TrueBreakoutConfig] = None,
                 **kwargs):
        """
        Initialize True Breakout Strategy.

        Args:
            symbol: Symbol to trade
            connector: MT5 connector instance
            order_manager: Order manager instance
            risk_manager: Risk manager instance
            trade_manager: Trade manager instance
            indicators: Technical indicators instance
            position_sizer: Position sizing plugin (injected by factory)
            config: Strategy configuration (optional, loads from env if None)
            **kwargs: Additional arguments (range_id, etc.)
        """
        # Initialize base strategy
        super().__init__(
            symbol=symbol,
            connector=connector,
            order_manager=order_manager,
            risk_manager=risk_manager,
            trade_manager=trade_manager,
            indicators=indicators,
            position_sizer=position_sizer
        )
        
        self.logger = get_logger()


        # Load configuration
        range_id = kwargs.get('range_id', '4H_5M')
        self.config = config or TrueBreakoutConfig.from_env(range_id)
        self.key = f"TB|{self.config.range_config.range_id}"  # Format: "TB|15M_1M"
        # Strategy state
        self.category: Optional[SymbolCategory] = None
        self.validation_thresholds = None

        # Reference candle tracking
        self.current_reference_candle: Optional[ReferenceCandle] = None

        # Unified breakout state (matches multi_range_strategy_engine.py)
        self.state = UnifiedBreakoutState()

        # Last processed candle times
        self.last_reference_candle_time: Optional[datetime] = None
        self.last_confirmation_candle_time: Optional[datetime] = None
        self.last_signal_time: Optional[datetime] = None

        # OPTIMIZATION #5 (Phase 2): Volume cache for efficient calculations
        # Provides O(1) rolling average instead of O(N) Pandas operations
        self.volume_cache = VolumeCache(lookback=20)  # 20-period volume average

        # Adaptive filter (will be initialized after symbol_params is loaded)
        self.adaptive_filter: Optional[AdaptiveFilter] = None

        # All validations must pass (AND logic)
        self._validation_mode = "all"

        # Auto-register validation methods using decorator
        auto_register_validations(self)

        self.logger.info(
            f"True Breakout Strategy initialized for {symbol} [{self.config.range_config.range_id}]",
            symbol,
            strategy_key=self.key
        )
    
    def initialize(self) -> bool:
        """
        Initialize strategy with category detection and parameter loading.
        
        Returns:
            True if initialization successful
        """
        try:
            # Get MT5 category
            mt5_category = None
            symbol_info = self.connector.get_symbol_info(self.symbol)
            if symbol_info:
                mt5_category = symbol_info.get('category')
            
            # Detect symbol category
            self.category = SymbolCategoryUtils.detect_category(self.symbol, mt5_category)

            # Load symbol parameters from repository
            default_params = SymbolParameters()  # Use default if category unknown
            self.symbol_params = SymbolParametersRepository.get_parameters(
                self.category, default_params
            )

            # Initialize adaptive filter
            trading_config = TradingConfig()
            self.adaptive_filter = AdaptiveFilter(
                symbol=self.symbol,
                config=trading_config.adaptive_filters,
                symbol_params=self.symbol_params
            )

            # Initialize filter state based on configuration
            if trading_config.adaptive_filters.start_with_filters_enabled:
                self.adaptive_filter.state.volume_confirmation_active = True
                self.adaptive_filter.state.divergence_confirmation_active = True
                self.symbol_params.volume_confirmation_enabled = True
                self.symbol_params.divergence_confirmation_enabled = True

            self.logger.info(
                f"Adaptive filters initialized: enabled={trading_config.adaptive_filters.use_adaptive_filters}",
                self.symbol, strategy_key=self.key
            )

            # Load validation thresholds
            self.validation_thresholds = ValidationThresholdsCalculator.get_thresholds(
                self.category
            )

            self.logger.info(
                f"Category: {self.category.value} | Range: {self.config.range_config.range_id} | "
                f"Retest Tolerance: {self.symbol_params.retest_range_percent:.4f} ({self.symbol_params.retest_range_percent*100:.2f}%)",
                self.symbol,
                strategy_key=self.key
            )

            # Initialize position sizer with base lot size from risk manager
            if self.position_sizer is not None:
                # Calculate initial lot size based on risk
                # Get current price for initial calculation
                current_price = self.connector.get_current_price(self.symbol)
                if current_price is None:
                    self.logger.error(f"Failed to get current price for {self.symbol}", self.symbol, strategy_key=self.key)
                    return False

                # Calculate a default stop loss for initialization (100 points)
                symbol_info = self.connector.get_symbol_info(self.symbol)
                if symbol_info is None:
                    self.logger.error(f"Failed to get symbol info for {self.symbol}", self.symbol, strategy_key=self.key)
                    return False

                point = symbol_info['point']
                default_sl = current_price - (DEFAULT_INITIALIZATION_SL_POINTS * point)  # Assume BUY for initialization

                initial_lot = self.risk_manager.calculate_lot_size(
                    symbol=self.symbol,
                    entry_price=current_price,
                    stop_loss=default_sl
                )
                self.position_sizer.initialize(initial_lot)
                self.logger.info(
                    f"Position sizer initialized: {self.position_sizer.get_name()} with {initial_lot:.2f} lots",
                    self.symbol,
                    strategy_key=self.key
                )

            self.is_initialized = True
            return True

        except Exception as e:
            self.logger.error(f"Error initializing True Breakout strategy: {e}", self.symbol, strategy_key=self.key)
            return False

    def on_tick(self) -> Optional[TradeSignal]:
        """
        Process tick event and check for trade signals.

        PERFORMANCE OPTIMIZATION: Event-driven signal generation
        Only processes signals when new candles form, not on every tick.
        This eliminates redundant get_candles() calls and indicator calculations.

        Returns:
            TradeSignal if conditions met, None otherwise
        """
        if not self.is_initialized:
            return None

        # Check if symbol is in active trading session (defensive check)
        # Note: TradingController already handles session checking, but this provides defense-in-depth
        if not self.connector.is_in_trading_session(self.symbol, suppress_logs=True):
            return None

        try:
            # OPTIMIZATION: Only check for new candles at timeframe boundaries
            # This avoids calling get_candles() on every tick
            current_time = self.connector.get_current_time()
            if current_time is None:
                return None

            # Get confirmation timeframe duration in minutes
            from src.utils.timeframe_converter import TimeframeConverter
            tf_minutes = TimeframeConverter.get_duration_minutes(self.config.range_config.breakout_timeframe)

            # Check if we're at a timeframe boundary (new candle could have formed)
            # Only check when current_time is aligned to the timeframe
            if current_time.minute % tf_minutes != 0:
                # Not at a timeframe boundary, skip processing
                return None

            # Check for new reference candle
            self._check_reference_candle()

            # Check for new confirmation candle
            if self._is_new_confirmation_candle():
                return self._process_confirmation_candle()

            return None

        except Exception as e:
            self.logger.error(f"Error in on_tick: {e}", self.symbol, strategy_key=self.key)
            return None

    def _check_reference_candle(self) -> Optional[ReferenceCandle]:
        """
        Check for new reference candle and fetch complete candle data.

        Implements fallback mechanism:
        1. Primary: Use today's reference candle if available
        2. Fallback: Use most recent reference candle from previous days if today's doesn't exist yet

        Returns:
            ReferenceCandle object with complete OHLCV data if new candle detected, None otherwise
        """
        try:
            # Get reference candles
            df = self.connector.get_candles(
                self.symbol,
                self.config.range_config.reference_timeframe,
                count=2
            )

            if df is None or len(df) < 2:
                # If no current reference candle exists, try fallback
                if self.current_reference_candle is None:
                    return self._get_reference_candle_with_fallback()
                return None

            # Get last closed candle
            last_candle = df.iloc[-2]
            candle_time = pd.Timestamp(last_candle['time']).to_pydatetime()

            # Check if this is a new candle
            if self.last_reference_candle_time is None or candle_time > self.last_reference_candle_time:
                # If using specific time, verify it matches
                if self.config.range_config.use_specific_time:
                    if (candle_time.hour == self.config.range_config.reference_time.hour and
                        candle_time.minute == self.config.range_config.reference_time.minute):
                        return self._update_reference_candle(last_candle, candle_time)
                    # Today's reference candle hasn't formed yet, try fallback
                    elif self.current_reference_candle is None:
                        return self._get_reference_candle_with_fallback()
                else:
                    # Use any candle of this timeframe
                    return self._update_reference_candle(last_candle, candle_time)

            return None

        except Exception as e:
            self.logger.error(f"Error checking reference candle: {e}", self.symbol, strategy_key=self.key, exc_info=True)
            return None

    def _get_reference_candle_with_fallback(self) -> Optional[ReferenceCandle]:
        """
        Get reference candle with fallback to previous days and fallback time.

        Searches backwards through historical candles to find the most recent valid
        reference candle when today's reference candle hasn't formed yet.

        Search order:
        1. Primary reference_time from previous days
        2. Fallback reference_time from previous days (if configured)
        3. Most recent candle (if use_specific_time=False)

        Returns:
            ReferenceCandle object if found, None otherwise
        """
        try:
            # Calculate lookback count based on timeframe to cover at least 7 days
            # For H4: 7 days * 24 hours / 4 hours = 42 candles, use 50 for safety
            # For M15: 7 days * 24 hours * 60 minutes / 15 minutes = 672 candles, use 700 for safety
            if self.config.range_config.reference_timeframe.startswith('H'):
                hours = int(self.config.range_config.reference_timeframe[1:])
                lookback_count = max(50, int((7 * 24) / hours) + 10)
            elif self.config.range_config.reference_timeframe.startswith('M'):
                minutes = int(self.config.range_config.reference_timeframe[1:])
                lookback_count = max(700, int((7 * 24 * 60) / minutes) + 10)
            else:
                lookback_count = 100  # Default

            # Get historical reference candles
            df = self.connector.get_candles(
                self.symbol,
                self.config.range_config.reference_timeframe,
                count=lookback_count
            )

            if df is None or len(df) < 2:
                self.logger.warning(
                    f"Could not retrieve {self.config.range_config.reference_timeframe} candles for fallback [{self.config.range_config.range_id}]",
                    self.symbol, strategy_key=self.key
                )
                return None

            if self.config.range_config.use_specific_time:
                # First, try to find primary reference_time
                for i in range(1, min(lookback_count, len(df))):
                    candle = df.iloc[-(i+1)]  # Get candle from end, skipping current
                    candle_time = pd.Timestamp(candle['time']).to_pydatetime()

                    # Check if this matches the primary reference time
                    if (candle_time.hour == self.config.range_config.reference_time.hour and
                        candle_time.minute == self.config.range_config.reference_time.minute):

                        # Update reference candle
                        self.current_reference_candle = ReferenceCandle(
                            time=candle_time,
                            open=float(candle['open']),
                            high=float(candle['high']),
                            low=float(candle['low']),
                            close=float(candle['close']),
                            timeframe=self.config.range_config.reference_timeframe
                        )
                        self.last_reference_candle_time = candle_time

                        # Calculate days ago
                        now = datetime.now(timezone.utc)
                        days_ago = (now.date() - candle_time.date()).days

                        self.logger.info(
                            f"*** FALLBACK (PRIMARY TIME): Using reference candle from {days_ago} day(s) ago [{self.config.range_config.range_id}] ***",
                            self.symbol,
                            strategy_key=self.key
                        )

                        return self.current_reference_candle

                # If primary time not found and fallback_reference_time is configured, try fallback time
                if self.config.range_config.fallback_reference_time is not None:
                    self.logger.info(
                        f"Primary reference time {self.config.range_config.reference_time.hour:02d}:{self.config.range_config.reference_time.minute:02d} not found, "
                        f"searching for fallback time {self.config.range_config.fallback_reference_time.hour:02d}:{self.config.range_config.fallback_reference_time.minute:02d} [{self.config.range_config.range_id}]",
                        self.symbol, strategy_key=self.key
                    )

                    for i in range(1, min(lookback_count, len(df))):
                        candle = df.iloc[-(i+1)]  # Get candle from end, skipping current
                        candle_time = pd.Timestamp(candle['time']).to_pydatetime()

                        # Check if this matches the fallback reference time
                        if (candle_time.hour == self.config.range_config.fallback_reference_time.hour and
                            candle_time.minute == self.config.range_config.fallback_reference_time.minute):

                            # Update reference candle
                            self.current_reference_candle = ReferenceCandle(
                                time=candle_time,
                                open=float(candle['open']),
                                high=float(candle['high']),
                                low=float(candle['low']),
                                close=float(candle['close']),
                                timeframe=self.config.range_config.reference_timeframe
                            )
                            self.last_reference_candle_time = candle_time

                            # Calculate days ago
                            now = datetime.now(timezone.utc)
                            days_ago = (now.date() - candle_time.date()).days

                            self.logger.info(
                                f"*** FALLBACK (FALLBACK TIME): Using reference candle from {days_ago} day(s) ago [{self.config.range_config.range_id}] ***",
                                self.symbol,
                                strategy_key=self.key
                            )

                            return self.current_reference_candle

                # If we get here, neither primary nor fallback time was found
                if self.config.range_config.fallback_reference_time is not None:
                    self.logger.warning(
                        f"No reference candle found for primary time {self.config.range_config.reference_time.hour:02d}:{self.config.range_config.reference_time.minute:02d} "
                        f"or fallback time {self.config.range_config.fallback_reference_time.hour:02d}:{self.config.range_config.fallback_reference_time.minute:02d} "
                        f"in last {lookback_count} candles [{self.config.range_config.range_id}]",
                        self.symbol, strategy_key=self.key
                    )
                else:
                    self.logger.warning(
                        f"No reference candle found for {self.config.range_config.reference_time.hour:02d}:{self.config.range_config.reference_time.minute:02d} UTC "
                        f"in last {lookback_count} candles [{self.config.range_config.range_id}]",
                        self.symbol, strategy_key=self.key
                    )
            else:
                # use_specific_time=False: Use the most recent closed candle
                candle = df.iloc[-2]  # Get second-to-last candle (most recent closed)
                candle_time = pd.Timestamp(candle['time']).to_pydatetime()

                self.current_reference_candle = ReferenceCandle(
                    time=candle_time,
                    open=float(candle['open']),
                    high=float(candle['high']),
                    low=float(candle['low']),
                    close=float(candle['close']),
                    timeframe=self.config.range_config.reference_timeframe
                )
                self.last_reference_candle_time = candle_time

                self.logger.info(
                    f"*** FALLBACK: Using most recent reference candle [{self.config.range_config.range_id}] ***",
                    self.symbol,
                    strategy_key=self.key
                )

                return self.current_reference_candle

            return None

        except Exception as e:
            self.logger.error(f"Error in fallback reference candle retrieval: {e}", self.symbol, strategy_key=self.key, exc_info=True)
            return None

    def _update_reference_candle(self, candle_data, candle_time: datetime) -> ReferenceCandle:
        """
        Update reference candle with complete OHLCV data and reset state.

        OPTIMIZATION #5 (Phase 2): Resets volume cache when reference changes.

        Args:
            candle_data: Pandas Series containing candle data
            candle_time: Candle timestamp

        Returns:
            ReferenceCandle object with complete OHLCV data
        """
        self.current_reference_candle = ReferenceCandle(
            time=candle_time,
            open=float(candle_data['open']),
            high=float(candle_data['high']),
            low=float(candle_data['low']),
            close=float(candle_data['close']),
            timeframe=self.config.range_config.reference_timeframe
        )

        self.last_reference_candle_time = candle_time

        # Reset unified breakout state
        self.state.reset_all()

        # OPTIMIZATION #5: Reset volume cache when reference candle changes
        self.volume_cache.reset()

        self.logger.info(
            f"*** NEW REFERENCE CANDLE [{self.config.range_config.range_id}] ***",
            self.symbol,
            strategy_key=self.key
        )

        return self.current_reference_candle

    def _is_new_confirmation_candle(self) -> bool:
        """
        Check if a new confirmation candle has formed.

        OPTIMIZATION #5 (Phase 2): Updates volume cache when new candle detected.
        """
        try:
            df = self.connector.get_candles(
                self.symbol,
                self.config.range_config.breakout_timeframe,
                count=2
            )

            if df is None or len(df) < 2:
                return False

            last_candle = df.iloc[-2]
            candle_time = pd.Timestamp(last_candle['time']).to_pydatetime()

            if self.last_confirmation_candle_time is None or candle_time > self.last_confirmation_candle_time:
                self.last_confirmation_candle_time = candle_time

                # OPTIMIZATION #5: Update volume cache with new candle
                volume = last_candle['tick_volume']
                self.volume_cache.update(volume)

                return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking confirmation candle: {e}", self.symbol, strategy_key=self.key)
            return False

    def _process_confirmation_candle(self) -> Optional[TradeSignal]:
        """
        Process confirmation candle using correct trading flow.

        Implements the 3-stage flow from multi_range_strategy_engine.py:
        - Stage 1: Unified breakout detection
        - Stage 2: Strategy classification (TRUE BREAKOUT only)
        - Stage 3 & 4: Check for signals

        Returns:
            TradeSignal if all conditions met, None otherwise
        """
        if self.current_reference_candle is None:
            return None

        try:
            # Get current confirmation candle
            df = self.connector.get_candles(
                self.symbol,
                self.config.range_config.breakout_timeframe,
                count=2
            )

            if df is None or len(df) < 2:
                return None

            candle = df.iloc[-2]
            candle_data = CandleData(
                open=float(candle['open']),
                high=float(candle['high']),
                low=float(candle['low']),
                close=float(candle['close']),
                volume=int(candle['tick_volume']),
                time=pd.Timestamp(candle['time']).to_pydatetime()
            )

            # === STAGE 1: UNIFIED BREAKOUT DETECTION ===
            # Check for timeout FIRST (before detecting new breakouts)
            self._check_breakout_timeout(candle_data.time)

            # Detect breakouts in both directions
            self._detect_breakout(candle_data)

            # === STAGE 2: STRATEGY CLASSIFICATION ===
            self._classify_true_breakout_strategy(candle_data)

            # === STAGE 3 & 4: CHECK FOR SIGNALS ===
            signal = self._check_true_breakout_signals(candle_data)
            if signal:
                return signal

            # === CLEANUP: Reset if strategy rejected ===
            # Note: In multi-range engine, this checks both_strategies_rejected()
            # For single strategy, we just check if our strategy was rejected
            if self.state.true_buy_rejected or self.state.true_sell_rejected:
                self.logger.info(f">>> TRUE BREAKOUT REJECTED [{self.config.range_config.range_id}] - Resetting <<<", self.symbol, strategy_key=self.key)
                self.state.reset_all()

            return None

        except Exception as e:
            self.logger.error(f"Error processing confirmation candle: {e}", self.symbol, strategy_key=self.key)
            return None

    def _check_breakout_timeout(self, current_time: datetime):
        """
        Check if existing breakouts have timed out.
        Matches logic from multi_range_strategy_engine.py
        """
        # Calculate timeout using TimeframeConverter
        minutes_per_candle = TimeframeConverter.get_minutes_per_candle(
            self.config.range_config.breakout_timeframe
        )
        timeout_minutes = self.config.breakout_timeout_candles * minutes_per_candle
        timeout_delta = timedelta(minutes=timeout_minutes)

        # Check breakout ABOVE timeout
        if self.state.breakout_above_detected and self.state.breakout_above_time:
            age = current_time - self.state.breakout_above_time
            age_minutes = int(age.total_seconds() / 60)

            if age.total_seconds() < 0:
                self.logger.warning(f"Negative breakout age detected: {age.total_seconds()}s - possible timezone issue", self.symbol, strategy_key=self.key)
                return

            if age > timeout_delta:

                self.logger.info(f">>> BREAKOUT ABOVE TIMEOUT [{self.config.range_config.range_id}] - Resetting <<<", self.symbol, strategy_key=self.key)

                self.state.reset_breakout_above()

        # Check breakout BELOW timeout
        if self.state.breakout_below_detected and self.state.breakout_below_time:
            age = current_time - self.state.breakout_below_time
            age_minutes = int(age.total_seconds() / 60)

            if age.total_seconds() < 0:
                self.logger.warning(f"Negative breakout age detected: {age.total_seconds()}s - possible timezone issue", self.symbol, strategy_key=self.key)
                return

            if age > timeout_delta:

                self.logger.info(f">>> BREAKOUT BELOW TIMEOUT [{self.config.range_config.range_id}] - Resetting <<<", self.symbol, strategy_key=self.key)

                self.state.reset_breakout_below()

    def _detect_breakout(self, candle: CandleData):
        """
        STAGE 1: Unified breakout detection.
        Matches logic from multi_range_strategy_engine.py
        """
        candle_ref = self.current_reference_candle

        # Check for breakout ABOVE reference high
        if not self.state.breakout_above_detected:
            # Validate: Open INSIDE range AND Close ABOVE high
            open_inside_range = candle.open >= candle_ref.low and candle.open <= candle_ref.high
            close_above_high = candle.close > candle_ref.high

            if open_inside_range and close_above_high:
                self.state.breakout_above_detected = True
                self.state.breakout_above_volume = candle.volume
                self.state.breakout_above_time = candle.time

                self.logger.info(
                    f">>> BREAKOUT ABOVE HIGH DETECTED [{self.config.range_config.range_id}] <<<",
                    self.symbol,
                    strategy_key=self.key
                )

        # Check for breakout BELOW reference low
        if not self.state.breakout_below_detected:
            # Validate: Open INSIDE range AND Close BELOW low
            open_inside_range = candle.open >= candle_ref.low and candle.open <= candle_ref.high
            close_below_low = candle.close < candle_ref.low

            if open_inside_range and close_below_low:
                self.state.breakout_below_detected = True
                self.state.breakout_below_volume = candle.volume
                self.state.breakout_below_time = candle.time

                self.logger.info(
                    f">>> BREAKOUT BELOW LOW DETECTED [{self.config.range_config.range_id}] <<<",
                    self.symbol,
                    strategy_key=self.key
                )

    def _classify_true_breakout_strategy(self, candle: CandleData):
        """
        STAGE 2: Strategy classification for TRUE BREAKOUT.
        Matches logic from multi_range_strategy_engine.py

        OPTIMIZATION #5 (Phase 2): Uses cached volume average if available.
        """
        # OPTIMIZATION #5: Use cached average if available
        if not self.volume_cache.is_ready():
            # Fallback to Pandas for first few candles
            df = self.connector.get_candles(
                self.symbol,
                self.config.range_config.breakout_timeframe,
                count=20
            )
            if df is None:
                return

            # Calculate average volume using Pandas
            avg_volume = self.indicators.calculate_average_volume(
                df['tick_volume'],
                period=20
            )
        else:
            # Use cached average (much faster - O(1) instead of O(N))
            avg_volume = self.volume_cache.get_average()

        # === CLASSIFY BREAKOUT ABOVE (TRUE BUY) ===
        if self.state.breakout_above_detected and not self.state.true_buy_qualified:
            volume = self.state.breakout_above_volume

            # Check if qualifies for TRUE BUY (high volume continuation)
            is_high_volume = self.indicators.is_true_breakout_volume_high(
                volume, avg_volume,
                self.config.min_breakout_volume_multiplier,
                self.symbol
            )

            self.state.true_buy_qualified = True
            self.state.true_buy_volume_ok = is_high_volume

            vol_status = "✓" if is_high_volume else "✗"
            self.logger.info(f">>> TRUE BUY QUALIFIED [{self.config.range_config.range_id}] (High Vol {vol_status}) <<<", self.symbol, strategy_key=self.key)
            self.logger.info("Waiting for continuation above reference high...", self.symbol, strategy_key=self.key)

        # === CLASSIFY BREAKOUT BELOW (TRUE SELL) ===
        if self.state.breakout_below_detected and not self.state.true_sell_qualified:
            volume = self.state.breakout_below_volume

            # Check if qualifies for TRUE SELL (high volume continuation)
            is_high_volume = self.indicators.is_true_breakout_volume_high(
                volume, avg_volume,
                self.config.min_breakout_volume_multiplier,
                self.symbol
            )

            self.state.true_sell_qualified = True
            self.state.true_sell_volume_ok = is_high_volume

            vol_status = "✓" if is_high_volume else "✗"
            self.logger.info(f">>> TRUE SELL QUALIFIED [{self.config.range_config.range_id}] (High Vol {vol_status}) <<<", self.symbol, strategy_key=self.key)
            self.logger.info("Waiting for continuation below reference low...", self.symbol, strategy_key=self.key)

    def _check_true_breakout_signals(self, candle: CandleData) -> Optional[TradeSignal]:
        """
        STAGE 3 & 4: Check TRUE BREAKOUT strategies for signals.
        Matches logic from multi_range_strategy_engine.py
        """
        candle_ref = self.current_reference_candle

        # === TRUE BUY: Check for retest and continuation ===
        if self.state.true_buy_qualified:
            # First check for retest (pullback to reference high)
            if not self.state.true_buy_retest_detected:
                # Ensure retest happens on a later candle than the breakout
                breakout_time = self.state.breakout_above_time
                if breakout_time and candle.time <= breakout_time:
                    return None

                # Calculate intelligent retest tolerance (handles high-value instruments)
                retest_range = self._calculate_retest_tolerance(candle_ref.high)

                # Check if candle touched or came close to the reference high
                # For bullish retest: check if candle's LOW touched the level (wick check)
                # AND close is above the level (rejection/bounce)
                touched_level = candle.low <= (candle_ref.high + retest_range)
                closed_above = candle.close >= candle_ref.high

                # Check retest volume (should be lower than breakout volume)
                # This indicates weak selling pressure during the pullback
                breakout_volume = self.state.breakout_above_volume
                retest_volume_ok = candle.volume < breakout_volume if breakout_volume > 0 else True
                volume_ratio = (candle.volume / breakout_volume) if breakout_volume > 0 else 0.0

                if touched_level and closed_above:
                    self.state.true_buy_retest_detected = True
                    self.state.true_buy_retest_ok = True
                    vol_status = "✓" if retest_volume_ok else "✗"
                    self.logger.info(f">>> TRUE BUY RETEST DETECTED [{self.config.range_config.range_id}] (Retest Vol {vol_status}) <<<", self.symbol, strategy_key=self.key)
                    self.logger.info(f"Candle Low: {candle.low:.5f} | Close: {candle.close:.5f}", self.symbol, strategy_key=self.key)
                    self.logger.info(f"Reference High: {candle_ref.high:.5f}", self.symbol, strategy_key=self.key)
                    self.logger.info(f"Retest Range: {retest_range:.5f}", self.symbol, strategy_key=self.key)
                    self.logger.info(f"Retest Volume: {candle.volume} | Breakout Volume: {breakout_volume} | Ratio: {volume_ratio:.2f}x", self.symbol, strategy_key=self.key)
                    return None

            # After retest detected on previous candle, check for continuation on current candle
            if not self.state.true_buy_continuation_detected:
                if candle.close > candle_ref.high:
                    self.state.true_buy_continuation_detected = True
                    self.state.true_buy_continuation_volume = candle.volume

                    # Check continuation volume (tracked but not required)
                    continuation_volume_ok = self._is_continuation_volume_high(candle.volume)
                    self.state.true_buy_continuation_volume_ok = continuation_volume_ok

                    vol_status = "✓" if continuation_volume_ok else "✗"
                    self.logger.info(f">>> TRUE BUY CONTINUATION DETECTED [{self.config.range_config.range_id}] (Cont Vol {vol_status}) <<<", self.symbol, strategy_key=self.key)

                    self.logger.info(f"*** TRUE BUY SIGNAL GENERATED [{self.config.range_config.range_id}] ***", self.symbol, strategy_key=self.key)
                    return self._generate_buy_signal(candle)

        # === TRUE SELL: Check for retest and continuation ===
        if self.state.true_sell_qualified:
            # First check for retest (pullback to reference low)
            if not self.state.true_sell_retest_detected:
                # Ensure retest happens on a later candle than the breakout
                breakout_time = self.state.breakout_below_time
                if breakout_time and candle.time <= breakout_time:
                    return None

                # Calculate intelligent retest tolerance (handles high-value instruments)
                retest_range = self._calculate_retest_tolerance(candle_ref.low)

                # Check if candle touched or came close to the reference low
                # For bearish retest: check if candle's HIGH touched the level (wick check)
                # AND close is below the level (rejection/bounce)
                touched_level = candle.high >= (candle_ref.low - retest_range)
                closed_below = candle.close <= candle_ref.low

                # Check retest volume (should be lower than breakout volume)
                # This indicates weak buying pressure during the pullback
                breakout_volume = self.state.breakout_below_volume
                retest_volume_ok = candle.volume < breakout_volume if breakout_volume > 0 else True
                volume_ratio = (candle.volume / breakout_volume) if breakout_volume > 0 else 0.0

                if touched_level and closed_below:
                    self.state.true_sell_retest_detected = True
                    self.state.true_sell_retest_ok = True
                    vol_status = "✓" if retest_volume_ok else "✗"
                    self.logger.info(f">>> TRUE SELL RETEST DETECTED [{self.config.range_config.range_id}] (Retest Vol {vol_status}) <<<", self.symbol, strategy_key=self.key)
                    return None

            # After retest detected on previous candle, check for continuation on current candle
            if not self.state.true_sell_continuation_detected:
                if candle.close < candle_ref.low:
                    self.state.true_sell_continuation_detected = True
                    self.state.true_sell_continuation_volume = candle.volume

                    # Check continuation volume (tracked but not required)
                    continuation_volume_ok = self._is_continuation_volume_high(candle.volume)
                    self.state.true_sell_continuation_volume_ok = continuation_volume_ok

                    vol_status = "✓" if continuation_volume_ok else "✗"
                    self.logger.info(f">>> TRUE SELL CONTINUATION DETECTED [{self.config.range_config.range_id}] (Cont Vol {vol_status}) <<<", self.symbol, strategy_key=self.key)
                    self.logger.info(f"*** TRUE SELL SIGNAL GENERATED [{self.config.range_config.range_id}] ***", self.symbol, strategy_key=self.key)
                    return self._generate_sell_signal(candle)

        return None

    def _calculate_retest_tolerance(self, reference_price: float) -> float:
        """
        Calculate intelligent retest tolerance based on symbol parameters and price scale.

        This method solves the issue where percentage-based tolerance creates
        inappropriately large zones for high-value instruments (e.g., BTCJPY at 14M).

        Modes:
        - 'percent': Force percentage-based tolerance (good for forex)
        - 'points': Force absolute point-based tolerance (good for crypto)
        - 'auto': Intelligently choose based on price scale

        Args:
            reference_price: The breakout level price

        Returns:
            Absolute tolerance value in price units

        Example:
            For BTCJPY at 14,611,144:
            - Old way: 0.5% = 73,056 points (TOO LARGE!)
            - New way: 20,000 points (reasonable)
        """
        if not self.symbol_params:
            # Fallback to legacy percentage-based
            return reference_price * RETEST_RANGE_PERCENT

        mode = self.symbol_params.retest_tolerance_mode

        # Force percentage mode
        if mode == 'percent':
            tolerance = reference_price * self.symbol_params.retest_range_percent
            self.logger.debug(
                f"Retest tolerance (percent mode): {tolerance:.2f} "
                f"({self.symbol_params.retest_range_percent*100:.3f}% of {reference_price:.2f})",
                self.symbol
            )
            return tolerance

        # Force points mode
        if mode == 'points':
            tolerance = self.symbol_params.retest_range_points
            self.logger.debug(
                f"Retest tolerance (points mode): {tolerance:.2f} points",
                self.symbol
            )
            return tolerance

        # Auto mode: Intelligent selection based on price scale
        # Strategy: Use percentage for low-value instruments, but cap the absolute value
        # to prevent huge tolerance zones on high-value instruments

        # Calculate percentage-based tolerance
        pct_tolerance = reference_price * self.symbol_params.retest_range_percent

        # For high-value instruments (price > 1000), cap at configured points
        if reference_price > 1000.0 and self.symbol_params.retest_range_points > 0:
            # Use the SMALLER of: percentage-based OR fixed points
            # This prevents huge zones on crypto like BTCJPY while allowing
            # reasonable zones on ETHUSD
            tolerance = min(pct_tolerance, self.symbol_params.retest_range_points)
        else:
            # Low-value instrument - use percentage
            tolerance = pct_tolerance
        return tolerance

    def _is_continuation_volume_high(self, continuation_volume: int) -> bool:
        """Check if continuation volume is high (tracked but not required)."""
        df = self.connector.get_candles(
            self.symbol,
            self.config.range_config.breakout_timeframe,
            count=20
        )
        if df is None:
            return False

        avg_volume = self.indicators.calculate_average_volume(
            df['tick_volume'],
            period=20
        )

        return self.indicators.is_continuation_volume_high(
            continuation_volume, avg_volume,
            self.config.min_continuation_volume_multiplier,
            self.symbol
        )

    @validation_check(abbreviation="BV", order=1, description="Check breakout volume is high", required=False)
    def _check_breakout_volume(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if initial breakout had high volume (required for true breakout).

        Args:
            signal_data: Dictionary containing:
                - 'breakout_volume': int - Volume of initial breakout candle
                - 'signal_direction': int (1 for BUY, -1 for SELL)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        signal_direction = signal_data.get('signal_direction', 0)

        # Get breakout volume from state based on direction
        if signal_direction > 0:  # BUY
            breakout_volume = self.state.breakout_above_volume
            volume_ok = self.state.true_buy_volume_ok
        elif signal_direction < 0:  # SELL
            breakout_volume = self.state.breakout_below_volume
            volume_ok = self.state.true_sell_volume_ok
        else:
            return ValidationResult(
                passed=False,
                method_name="_check_breakout_volume",
                reason="Invalid signal direction"
            )

        if breakout_volume is None or breakout_volume <= 0:
            return ValidationResult(
                passed=False,
                method_name="_check_breakout_volume",
                reason="No breakout volume data available"
            )

        # The volume check was already performed during qualification
        # We just validate that it passed
        direction_str = "BUY" if signal_direction > 0 else "SELL"

        return ValidationResult(
            passed=volume_ok,
            method_name="_check_breakout_volume",
            reason=f"Breakout volume for {direction_str} {'meets' if volume_ok else 'does not meet'} minimum threshold (vol={breakout_volume:.0f})"
        )

    @validation_check(abbreviation="RT", order=2, description="Check retest of breakout level")
    def _check_retest_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if retest of breakout level was detected and confirmed.

        Args:
            signal_data: Dictionary containing:
                - 'signal_direction': int (1 for BUY, -1 for SELL)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        signal_direction = signal_data.get('signal_direction', 0)

        # Get retest status from state based on direction
        if signal_direction > 0:  # BUY
            retest_detected = self.state.true_buy_retest_detected
            retest_ok = self.state.true_buy_retest_ok
        elif signal_direction < 0:  # SELL
            retest_detected = self.state.true_sell_retest_detected
            retest_ok = self.state.true_sell_retest_ok
        else:
            return ValidationResult(
                passed=False,
                method_name="_check_retest_confirmation",
                reason="Invalid signal direction"
            )

        direction_str = "BUY" if signal_direction > 0 else "SELL"

        if not retest_detected:
            return ValidationResult(
                passed=False,
                method_name="_check_retest_confirmation",
                reason=f"Retest not detected for {direction_str} signal"
            )

        return ValidationResult(
            passed=retest_ok,
            method_name="_check_retest_confirmation",
            reason=f"Retest {'confirmed' if retest_ok else 'failed'} for {direction_str} signal"
        )

    @validation_check(abbreviation="CV", order=3, description="Check continuation volume meets threshold", required=False)
    def _check_continuation_volume(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if continuation volume meets configured requirements.

        Args:
            signal_data: Dictionary containing:
                - 'continuation_volume': int - Volume of continuation candle
                - 'signal_direction': int (1 for BUY, -1 for SELL)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        signal_direction = signal_data.get('signal_direction', 0)
        continuation_volume = signal_data.get('continuation_volume', 0)

        if continuation_volume <= 0:
            return ValidationResult(
                passed=True,  # Skip check if no volume data
                method_name="_check_continuation_volume",
                reason="No continuation volume data available, skipping"
            )

        # Get continuation volume status from state based on direction
        if signal_direction > 0:  # BUY
            volume_ok = self.state.true_buy_continuation_volume_ok
        elif signal_direction < 0:  # SELL
            volume_ok = self.state.true_sell_continuation_volume_ok
        else:
            return ValidationResult(
                passed=True,  # Skip if invalid direction
                method_name="_check_continuation_volume",
                reason="Invalid signal direction, skipping"
            )

        direction_str = "BUY" if signal_direction > 0 else "SELL"

        return ValidationResult(
            passed=volume_ok,
            method_name="_check_continuation_volume",
            reason=f"Continuation volume for {direction_str} {'meets' if volume_ok else 'does not meet'} threshold (vol={continuation_volume:.0f})"
        )

    def _generate_buy_signal(self, candle: CandleData) -> Optional[TradeSignal]:
        """Generate BUY signal with proper SL/TP calculation."""
        try:
            # Check if we already have a BUY position for this symbol/strategy
            # This prevents duplicate signal generation while a position is open
            existing_positions = self.connector.get_positions(
                symbol=self.symbol,
                magic_number=self.magic_number
            )

            for pos in existing_positions:
                if pos.position_type == PositionType.BUY:
                    # Extract strategy type from comment (format: "TB|15M_1M|BV")
                    parts = pos.comment.split('|') if '|' in pos.comment else []
                    comment_strategy = parts[0] if len(parts) > 0 else ''
                    comment_range = parts[1] if len(parts) > 1 else ''

                    # Check if this is the same strategy and range
                    if comment_strategy == "TB" and comment_range == self.config.range_config.range_id:
                        self.logger.debug(
                            f"Suppressing BUY signal - position already open (ticket: {pos.ticket})",
                            self.symbol, strategy_key=self.key
                        )
                        return None

            # Calculate entry price first (needed for validation)
            entry_price = candle.close

            # Calculate stop loss using pattern-based position sizer if available
            if isinstance(self.position_sizer, PatternBasedPositionSizer):
                try:
                    # Use pattern-based SL calculation (considers reference candle + breakout pattern)
                    sl_result = self.position_sizer.calculate_stop_loss_for_buy(
                        reference_candle=self.current_reference_candle,
                        breakout_candles=None  # Can be extended to include breakout candles
                    )
                    stop_loss = sl_result.stop_loss

                    self.logger.debug(
                        f"Pattern-based SL for BUY: {stop_loss:.5f} "
                        f"(Pattern Low: {sl_result.pattern_low:.5f}, Spread: {sl_result.spread_applied:.5f})",
                        self.symbol, strategy_key=self.key
                    )
                except ValueError as e:
                    self.logger.error(
                        f"Failed to calculate pattern-based stop loss for BUY: {e}",
                        self.symbol, strategy_key=self.key
                    )
                    return None
            else:
                # Fallback to original SL calculation
                symbol_info = self.connector.get_symbol_info(self.symbol)
                if symbol_info is None:
                    self.logger.error(
                        f"Failed to get symbol info for {self.symbol}",
                        self.symbol,
                        strategy_key=self.key
                    )
                    return None

                point = symbol_info['point']
                digits = symbol_info['digits']

                # Convert buffer pips to price
                pip_size = point * 10
                buffer = self.config.sl_buffer_pips * pip_size

                # Stop loss below reference low with buffer
                stop_loss = self.current_reference_candle.low - buffer
                stop_loss = round(stop_loss, digits)

            # Validate stop loss distance
            sl_distance = abs(entry_price - stop_loss)
            if sl_distance <= 0:
                self.logger.error(
                    f"Invalid stop loss for BUY signal - SL distance is zero or negative",
                    self.symbol, strategy_key=self.key
                )
                self.logger.error(
                    f"Entry: {entry_price:.5f}, SL: {stop_loss:.5f}, Distance: {sl_distance:.5f}",
                    self.symbol, strategy_key=self.key
                )
                return None

            # Verify SL is on correct side for BUY
            if stop_loss >= entry_price:
                self.logger.error(
                    f"Invalid stop loss for BUY signal - SL must be below entry price",
                    self.symbol, strategy_key=self.key
                )
                self.logger.error(
                    f"Entry: {entry_price:.5f}, SL: {stop_loss:.5f}",
                    self.symbol, strategy_key=self.key
                )
                return None

            # Calculate take profit
            take_profit = entry_price + (sl_distance * self.config.risk_reward_ratio)

            # Calculate lot size from position sizer
            lot_size = self.get_lot_size()

            # Prepare signal data for validation
            signal_data = {
                'signal_direction': 1,  # BUY
                'continuation_volume': candle.volume,
                'current_price': entry_price
            }

            # Validate signal using dynamic validation system
            is_valid, validation_results = self._validate_signal(signal_data)

            if not is_valid:
                failed_checks = [r for r in validation_results if not r.passed]
                for result in failed_checks:
                    self.logger.debug(
                        f"TRUE BUY signal rejected by {result.method_name}: {result.reason}",
                        self.symbol, strategy_key=self.key
                    )
                self.logger.warning("TRUE BUY signal validation failed", self.symbol, strategy_key=self.key)
                self.state.true_buy_rejected = True
                return None
            else:
                self.logger.info("✓ TRUE BUY signal passed all validation filters", self.symbol, strategy_key=self.key)

            # Create signal
            signal = TradeSignal(
                symbol=self.symbol,
                signal_type=PositionType.BUY,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                lot_size=lot_size,
                timestamp=datetime.now(timezone.utc),
                reason=f"True Breakout BUY - {self.config.range_config.range_id}",
                max_spread_percent=0.1,
                comment=self.generate_trade_comment(PositionType.BUY)
            )

            # Update last signal time
            self.last_signal_time = datetime.now(timezone.utc)

            return signal

        except Exception as e:
            self.logger.error(f"Error generating BUY signal: {e}", self.symbol, strategy_key=self.key)
            return None

    def _generate_sell_signal(self, candle: CandleData) -> Optional[TradeSignal]:
        """Generate SELL signal with proper SL/TP calculation."""
        try:
            # Check if we already have a SELL position for this symbol/strategy
            # This prevents duplicate signal generation while a position is open
            existing_positions = self.connector.get_positions(
                symbol=self.symbol,
                magic_number=self.magic_number
            )

            for pos in existing_positions:
                if pos.position_type == PositionType.SELL:
                    # Extract strategy type from comment (format: "TB|15M_1M|BV")
                    parts = pos.comment.split('|') if '|' in pos.comment else []
                    comment_strategy = parts[0] if len(parts) > 0 else ''
                    comment_range = parts[1] if len(parts) > 1 else ''

                    # Check if this is the same strategy and range
                    if comment_strategy == "TB" and comment_range == self.config.range_config.range_id:
                        self.logger.debug(
                            f"Suppressing SELL signal - position already open (ticket: {pos.ticket})",
                            self.symbol, strategy_key=self.key
                        )
                        return None

            # Calculate entry price first (needed for validation)
            entry_price = candle.close

            # Calculate stop loss using pattern-based position sizer if available
            if isinstance(self.position_sizer, PatternBasedPositionSizer):
                try:
                    # Use pattern-based SL calculation (considers reference candle + breakout pattern)
                    sl_result = self.position_sizer.calculate_stop_loss_for_sell(
                        reference_candle=self.current_reference_candle,
                        breakout_candles=None  # Can be extended to include breakout candles
                    )
                    stop_loss = sl_result.stop_loss

                    self.logger.debug(
                        f"Pattern-based SL for SELL: {stop_loss:.5f} "
                        f"(Pattern High: {sl_result.pattern_high:.5f}, Spread: {sl_result.spread_applied:.5f})",
                        self.symbol, strategy_key=self.key
                    )
                except ValueError as e:
                    self.logger.error(
                        f"Failed to calculate pattern-based stop loss for SELL: {e}",
                        self.symbol, strategy_key=self.key
                    )
                    return None
            else:
                # Fallback to original SL calculation
                symbol_info = self.connector.get_symbol_info(self.symbol)
                if symbol_info is None:
                    self.logger.error(
                        f"Failed to get symbol info for {self.symbol}",
                        self.symbol,
                        strategy_key=self.key
                    )
                    return None

                point = symbol_info['point']
                digits = symbol_info['digits']

                # Convert buffer pips to price
                pip_size = point * 10
                buffer = self.config.sl_buffer_pips * pip_size

                # Stop loss above reference high with buffer
                stop_loss = self.current_reference_candle.high + buffer
                stop_loss = round(stop_loss, digits)

            # Validate stop loss distance
            sl_distance = abs(entry_price - stop_loss)
            if sl_distance <= 0:
                self.logger.error(
                    f"Invalid stop loss for SELL signal - SL distance is zero or negative",
                    self.symbol, strategy_key=self.key
                )
                self.logger.error(
                    f"Entry: {entry_price:.5f}, SL: {stop_loss:.5f}, Distance: {sl_distance:.5f}",
                    self.symbol, strategy_key=self.key
                )
                return None

            # Verify SL is on correct side for SELL
            if stop_loss <= entry_price:
                self.logger.error(
                    f"Invalid stop loss for SELL signal - SL must be above entry price",
                    self.symbol, strategy_key=self.key
                )
                self.logger.error(
                    f"Entry: {entry_price:.5f}, SL: {stop_loss:.5f}",
                    self.symbol, strategy_key=self.key
                )
                return None

            # Calculate take profit
            take_profit = entry_price - (sl_distance * self.config.risk_reward_ratio)

            # Calculate lot size from position sizer
            lot_size = self.get_lot_size()

            # Prepare signal data for validation
            signal_data = {
                'signal_direction': -1,  # SELL
                'continuation_volume': candle.volume,
                'current_price': entry_price
            }

            # Validate signal using dynamic validation system
            is_valid, validation_results = self._validate_signal(signal_data)

            if not is_valid:
                failed_checks = [r for r in validation_results if not r.passed]
                for result in failed_checks:
                    self.logger.debug(
                        f"TRUE SELL signal rejected by {result.method_name}: {result.reason}",
                        self.symbol, strategy_key=self.key
                    )
                self.logger.warning("TRUE SELL signal validation failed", self.symbol, strategy_key=self.key)
                self.state.true_sell_rejected = True
                return None
            else:
                self.logger.info("✓ TRUE SELL signal passed all validation filters", self.symbol, strategy_key=self.key)

            # Create signal
            signal = TradeSignal(
                symbol=self.symbol,
                signal_type=PositionType.SELL,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                lot_size=lot_size,
                timestamp=datetime.now(timezone.utc),
                reason=f"True Breakout SELL - {self.config.range_config.range_id}",
                max_spread_percent=0.1,
                comment=self.generate_trade_comment(PositionType.SELL)
            )

            # Update last signal time
            self.last_signal_time = datetime.now(timezone.utc)

            return signal

        except Exception as e:
            self.logger.error(f"Error generating SELL signal: {e}", self.symbol, strategy_key=self.key)
            return None



    def on_position_closed(self, symbol: str, profit: float,
                          volume: float, comment: str) -> None:
        """
        Handle position closure event.

        Args:
            symbol: Symbol of closed position
            profit: Profit/loss of closed position
            volume: Volume of closed position
            comment: Comment of closed position
        """
        if symbol != self.symbol:
            return

        # Log result
        is_win = profit > 0
        self.logger.info(
            f"Position closed: {'WIN' if is_win else 'LOSS'} ${profit:.2f}",
            self.symbol, strategy_key=self.key
        )

        # Update adaptive filter state
        if self.adaptive_filter is not None:
            self.adaptive_filter.on_trade_result(is_win)

        # Delegate to position sizer
        if self.position_sizer is not None:
            self.position_sizer.on_trade_closed(profit, volume)

    def get_status(self) -> Dict[str, Any]:
        """
        Get current strategy status.

        Returns:
            Dictionary with status information
        """
        return {
            'is_initialized': self.is_initialized,
            'symbol': self.symbol,
            'strategy': 'true_breakout',
            'range_id': self.config.range_config.range_id,
            'category': self.category.value if self.category else 'UNKNOWN',
            'last_signal_time': self.last_signal_time.isoformat() if self.last_signal_time else None,
            'breakout_above_detected': self.state.breakout_above_detected,
            'breakout_below_detected': self.state.breakout_below_detected,
            'true_buy_qualified': self.state.true_buy_qualified,
            'true_sell_qualified': self.state.true_sell_qualified,
            'true_buy_retest_detected': self.state.true_buy_retest_detected,
            'true_sell_retest_detected': self.state.true_sell_retest_detected,
            'true_buy_continuation_detected': self.state.true_buy_continuation_detected,
            'true_sell_continuation_detected': self.state.true_sell_continuation_detected,
            'reference_candle': {
                'high': self.current_reference_candle.high if self.current_reference_candle else None,
                'low': self.current_reference_candle.low if self.current_reference_candle else None,
                'time': self.current_reference_candle.time.isoformat() if self.current_reference_candle else None
            } if self.current_reference_candle else None,
            'config': {
                'range_timeframe': self.config.range_timeframe,
                'confirmation_timeframe': self.config.range_config.breakout_timeframe,
                'require_retest': self.config.require_retest,
                'risk_reward_ratio': self.config.risk_reward_ratio
            }
        }

    def shutdown(self) -> None:
        """Cleanup and shutdown the strategy."""
        self.logger.info(
            f"True Breakout strategy shutdown for {self.symbol} [{self.config.range_config.range_id}]",
            self.symbol, strategy_key=self.key
        )

