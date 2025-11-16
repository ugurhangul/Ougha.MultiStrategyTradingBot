"""
Fakeout Strategy - Reversal after failed breakout.

Implements a fakeout/reversal strategy that requires:
1. Low volume breakout (weak breakout)
2. Price reversal back into range
3. Optional divergence confirmation
4. Entry in reversal direction

Supports multiple range configurations (4H_5M, 15M_1M) operating independently.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import pandas as pd

from src.strategy.base_strategy import BaseStrategy, ValidationResult
from src.strategy.strategy_factory import register_strategy
from src.strategy.validation_decorator import validation_check, auto_register_validations
from src.models.data_models import (
    TradeSignal, PositionType, SymbolCategory, CandleData, ReferenceCandle,
    UnifiedBreakoutState
)
from src.core.mt5_connector import MT5Connector
from src.execution.order_manager import OrderManager
from src.execution.trade_manager import TradeManager
from src.risk.risk_manager import RiskManager
from src.risk.position_sizing.pattern_based_position_sizer import PatternBasedPositionSizer
from src.indicators.technical_indicators import TechnicalIndicators
from src.config.strategies import FakeoutConfig
from src.utils.strategy import (
    SymbolCategoryUtils, StopLossCalculator, ValidationThresholdsCalculator,
    SignalValidationHelpers, RangeDetector, BreakoutDetector
)
from src.utils.logger import get_logger
from src.utils.timeframe_converter import TimeframeConverter
from src.utils.volume_cache import VolumeCache  # OPTIMIZATION #5: Phase 2

# Constants
DEFAULT_INIT_SL_POINTS = 100  # Default stop loss points for initialization
DEFAULT_LOOKBACK_COUNT = 100  # Default lookback count for fallback
VOLUME_CALCULATION_PERIOD = 20  # Period for volume average calculation


@register_strategy(
    "fakeout",
    description="Fakeout/reversal strategy after failed breakout",
    enabled_by_default=True,
    requires_tick_data=False
)
class FakeoutStrategy(BaseStrategy):
    """
    Fakeout Strategy - Reversal after failed breakout.
    
    Strategy Logic:
    1. Detect low volume breakout (weak breakout)
    2. Wait for price to reverse back into range
    3. Optional: Check for divergence confirmation
    4. Enter trade in reversal direction
    5. Stop loss outside range, TP based on R:R
    """
    
    def __init__(self, symbol: str, connector: MT5Connector,
                 order_manager: OrderManager, risk_manager: RiskManager,
                 trade_manager: TradeManager, indicators: TechnicalIndicators,
                 position_sizer=None,
                 config: Optional[FakeoutConfig] = None,
                 **kwargs):
        """
        Initialize Fakeout Strategy.

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
        self.kwargs = kwargs
        # Load configuration
        range_id = kwargs.get('range_id', '4H_5M')
        self.config = config or FakeoutConfig.from_env(range_id)
        
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
        self.key = f"FB|{self.config.range_config.range_id}"  # Format: "FB|15M_1M"

        # OPTIMIZATION #5 (Phase 2): Volume cache for efficient calculations
        # Provides O(1) rolling average instead of O(N) Pandas operations
        self.volume_cache = VolumeCache(lookback=VOLUME_CALCULATION_PERIOD)

        # All validations must pass (AND logic)
        self._validation_mode = "all"

        # Validate configuration values
        self._validate_config()

        # Auto-register validation methods using decorator
        auto_register_validations(self)

        # Add divergence check if enabled (conditional validation - hybrid approach)
        if self.config.check_divergence:
            self._validation_methods.append("_check_divergence_confirmation")
            self._validation_abbreviations["_check_divergence_confirmation"] = "DIV"

        self.logger.info(
            f"Fakeout Strategy initialized for {symbol} [{self.config.range_config.range_id}]",
            symbol, strategy_key=self.key
        )

    def _validate_config(self) -> None:
        """
        Validate configuration values to ensure they are sensible.

        Raises:
            ValueError: If any configuration value is invalid
        """
        if self.config.max_breakout_volume_multiplier <= 0:
            raise ValueError(
                f"max_breakout_volume_multiplier must be positive, "
                f"got {self.config.max_breakout_volume_multiplier}"
            )

        if self.config.min_reversal_volume_multiplier <= 0:
            raise ValueError(
                f"min_reversal_volume_multiplier must be positive, "
                f"got {self.config.min_reversal_volume_multiplier}"
            )

        if self.config.risk_reward_ratio <= 0:
            raise ValueError(
                f"risk_reward_ratio must be positive, "
                f"got {self.config.risk_reward_ratio}"
            )

        if self.config.breakout_timeout_candles <= 0:
            raise ValueError(
                f"breakout_timeout_candles must be positive, "
                f"got {self.config.breakout_timeout_candles}"
            )

        if self.config.rsi_period <= 0:
            raise ValueError(
                f"rsi_period must be positive, "
                f"got {self.config.rsi_period}"
            )

        if self.config.divergence_lookback <= 0:
            raise ValueError(
                f"divergence_lookback must be positive, "
                f"got {self.config.divergence_lookback}"
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
            
            # Load validation thresholds
            self.validation_thresholds = ValidationThresholdsCalculator.get_thresholds(
                self.category
            )
            
            self.logger.info(
                f"Category: {self.category.value} | Range: {self.config.range_config.range_id}",
                self.symbol, strategy_key=self.key
            )

            # Initialize position sizer with base lot size from risk manager
            if self.position_sizer is not None:
                # Calculate initial lot size based on risk
                # Get current price for initial calculation
                current_price = self.connector.get_current_price(self.symbol)
                if current_price is None:
                    self.logger.error(
                        f"Failed to get current price for {self.symbol} - cannot initialize position sizer",
                        self.symbol, strategy_key=self.key
                    )
                    return False

                # Calculate a default stop loss for initialization
                symbol_info = self.connector.get_symbol_info(self.symbol)
                if symbol_info is None:
                    self.logger.error(
                        f"Failed to get symbol info for {self.symbol} - cannot initialize position sizer",
                        self.symbol, strategy_key=self.key
                    )
                    return False

                point = symbol_info['point']
                default_sl = current_price - (DEFAULT_INIT_SL_POINTS * point)  # Assume BUY for initialization

                initial_lot = self.risk_manager.calculate_lot_size(
                    symbol=self.symbol,
                    entry_price=current_price,
                    stop_loss=default_sl
                )
                self.position_sizer.initialize(initial_lot)
                self.logger.info(
                    f"Position sizer initialized: {self.position_sizer.get_name()} with {initial_lot:.2f} lots",
                    self.symbol, strategy_key=self.key
                )

            self.is_initialized = True
            return True

        except Exception as e:
            self.logger.error(f"Error initializing Fakeout strategy: {e}", self.symbol, strategy_key=self.key)
            return False

    def on_tick(self) -> Optional[TradeSignal]:
        """
        Process tick event and check for trade signals.

        Returns:
            TradeSignal if conditions met, None otherwise
        """
        if not self.is_initialized:
            return None

        try:
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
            self.logger.error(f"Error checking reference candle: {e}", self.symbol, strategy_key=self.key)
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
            lookback_count = self._calculate_lookback_count()
            if lookback_count is None:
                return None

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
                            self.symbol, strategy_key=self.key
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
                                self.symbol, strategy_key=self.key
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
                    self.symbol, strategy_key=self.key
                )

                return self.current_reference_candle

            return None

        except Exception as e:
            self.logger.error(f"Error in fallback reference candle retrieval: {e}", self.symbol, strategy_key=self.key)
            return None

    def _calculate_lookback_count(self) -> Optional[int]:
        """
        Calculate lookback count based on timeframe to cover at least 7 days.

        Returns:
            Lookback count or None if timeframe is invalid
        """
        try:
            # For H4: 7 days * 24 hours / 4 hours = 42 candles, use 50 for safety
            # For M15: 7 days * 24 hours * 60 minutes / 15 minutes = 672 candles, use 700 for safety
            if self.config.range_config.reference_timeframe.startswith('H'):
                hours = int(self.config.range_config.reference_timeframe[1:])
                if hours <= 0:
                    self.logger.error(
                        f"Invalid timeframe hours: {hours} in {self.config.range_config.reference_timeframe}",
                        self.symbol, strategy_key=self.key
                    )
                    return None
                lookback_count = max(50, int((7 * 24) / hours) + 10)
            elif self.config.range_config.reference_timeframe.startswith('M'):
                minutes = int(self.config.range_config.reference_timeframe[1:])
                if minutes <= 0:
                    self.logger.error(
                        f"Invalid timeframe minutes: {minutes} in {self.config.range_config.reference_timeframe}",
                        self.symbol, strategy_key=self.key
                    )
                    return None
                lookback_count = max(700, int((7 * 24 * 60) / minutes) + 10)
            else:
                lookback_count = DEFAULT_LOOKBACK_COUNT  # Default

            return lookback_count
        except (ValueError, IndexError) as e:
            self.logger.error(
                f"Error parsing timeframe {self.config.range_config.reference_timeframe}: {e}",
                self.symbol, strategy_key=self.key
            )
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
        # This ensures we calculate volume for the new range
        self.volume_cache.reset()

        self.logger.info(
            f"*** NEW REFERENCE CANDLE [{self.config.range_config.range_id}] ***",
            self.symbol, strategy_key=self.key
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
        - Stage 2: Strategy classification (FALSE BREAKOUT only)
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
            self._classify_false_breakout_strategy(candle_data)

            # === STAGE 3 & 4: CHECK FOR SIGNALS ===
            signal = self._check_false_breakout_signals(candle_data)
            if signal:
                return signal

            # === CLEANUP: Reset if strategy rejected ===
            # Note: In multi-range engine, this checks both_strategies_rejected()
            # For single strategy, we just check if our strategy was rejected
            if self.state.false_buy_rejected or self.state.false_sell_rejected:
                self.logger.info(f">>> FALSE BREAKOUT REJECTED [{self.config.range_config.range_id}] - Resetting <<<", self.symbol, strategy_key=self.key)
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
                self.logger.info(
                    f">>> BREAKOUT ABOVE TIMEOUT [{self.config.range_config.range_id}] - Resetting <<<",
                    self.symbol, strategy_key=self.key
                )
                self.state.reset_breakout_above()

        # Check breakout BELOW timeout
        if self.state.breakout_below_detected and self.state.breakout_below_time:
            age = current_time - self.state.breakout_below_time
            age_minutes = int(age.total_seconds() / 60)

            if age.total_seconds() < 0:
                self.logger.warning(
                    f"Negative breakout age detected: {age.total_seconds()}s - possible timezone issue",
                    self.symbol, strategy_key=self.key
                )
                return

            if age > timeout_delta:
                self.logger.info(
                    f">>> BREAKOUT BELOW TIMEOUT [{self.config.range_config.range_id}] - Resetting <<<",
                    self.symbol, strategy_key=self.key
                )
                self.state.reset_breakout_below()

    def _detect_breakout(self, candle: CandleData) -> None:
        """
        STAGE 1: Unified breakout detection.
        Matches logic from multi_range_strategy_engine.py
        """
        candle_ref = self.current_reference_candle

        # Validate reference candle has a valid range
        if candle_ref.high == candle_ref.low:
            self.logger.warning(
                f"Reference candle has zero range (high == low = {candle_ref.high:.5f}), skipping breakout detection",
                self.symbol, strategy_key=self.key
            )
            return

        # === BREAKOUT ABOVE DETECTION ===
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
                    self.symbol, strategy_key=self.key
                )

        # === BREAKOUT BELOW DETECTION ===
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
                    self.symbol, strategy_key=self.key
                )


    def _classify_false_breakout_strategy(self, candle: CandleData) -> None:
        """
        STAGE 2: Strategy classification for FALSE BREAKOUT.
        Matches logic from multi_range_strategy_engine.py

        OPTIMIZATION #5 (Phase 2): Uses cached volume average if available.
        """
        # OPTIMIZATION #5: Use cached average if available
        if not self.volume_cache.is_ready():
            # Fallback to Pandas for first few candles
            df = self.connector.get_candles(
                self.symbol,
                self.config.range_config.breakout_timeframe,
                count=VOLUME_CALCULATION_PERIOD
            )
            if df is None:
                self.logger.warning(
                    f"Failed to fetch candles for volume calculation",
                    self.symbol, strategy_key=self.key
                )
                return

            # Calculate average volume using Pandas
            avg_volume = self.indicators.calculate_average_volume(
                df['tick_volume'],
                period=VOLUME_CALCULATION_PERIOD
            )
        else:
            # Use cached average (much faster - O(1) instead of O(N))
            avg_volume = self.volume_cache.get_average()

        # === CLASSIFY BREAKOUT ABOVE (FALSE SELL - reversal down) ===
        if self.state.breakout_above_detected and not self.state.false_sell_qualified:
            volume = self.state.breakout_above_volume

            # Check if qualifies for FALSE SELL (low volume reversal)
            is_low_volume = self.indicators.is_breakout_volume_low(
                volume, avg_volume,
                self.config.max_breakout_volume_multiplier,
                self.symbol
            )

            self.state.false_sell_qualified = True
            self.state.false_sell_volume_ok = is_low_volume

            vol_status = "✓" if is_low_volume else "✗"
            self.logger.info(f">>> FALSE SELL QUALIFIED [{self.config.range_config.range_id}] (Low Vol {vol_status}) <<<", self.symbol, strategy_key=self.key)

        # === CLASSIFY BREAKOUT BELOW (FALSE BUY - reversal up) ===
        if self.state.breakout_below_detected and not self.state.false_buy_qualified:
            volume = self.state.breakout_below_volume

            # Check if qualifies for FALSE BUY (low volume reversal)
            is_low_volume = self.indicators.is_breakout_volume_low(
                volume, avg_volume,
                self.config.max_breakout_volume_multiplier,
                self.symbol
            )

            self.state.false_buy_qualified = True
            self.state.false_buy_volume_ok = is_low_volume

            vol_status = "✓" if is_low_volume else "✗"
            self.logger.info(
                f">>> FALSE BUY QUALIFIED [{self.config.range_config.range_id}] (Low Vol {vol_status}) <<<",
                self.symbol, strategy_key=self.key
            )

    def _check_false_breakout_signals(self, candle: CandleData) -> Optional[TradeSignal]:
        """
        STAGE 3 & 4: Check FALSE BREAKOUT strategies for signals.
        Matches logic from multi_range_strategy_engine.py
        """
        candle_ref = self.current_reference_candle

        # === FALSE SELL: Check for reversal and confirmation ===
        if self.state.false_sell_qualified:
            breakout_time = self.state.breakout_above_time

            # First check for reversal (price back into range)
            if not self.state.false_sell_reversal_detected:
                # Ensure reversal happens on a later candle than the breakout
                if breakout_time and candle.time <= breakout_time:
                    return None

                if candle.close < candle_ref.high:
                    self.state.false_sell_reversal_detected = True
                    self.state.false_sell_reversal_ok = True
                    self.state.false_sell_reversal_time = candle.time
                    self.logger.info(
                        f">>> FALSE SELL REVERSAL DETECTED [{self.config.range_config.range_id}] <<<",
                        self.symbol, strategy_key=self.key
                    )
                    # Return early to wait for next candle before checking confirmation
                    return None

            # After reversal detected on a previous candle, check for confirmation
            if self.state.false_sell_reversal_detected and not self.state.false_sell_confirmation_detected:
                reversal_time = self.state.false_sell_reversal_time

                # Ensure confirmation happens after the reversal candle
                if reversal_time and candle.time <= reversal_time:
                    return None

                if candle.close < candle_ref.high:
                    self.state.false_sell_confirmation_detected = True
                    self.state.false_sell_confirmation_volume = candle.volume

                    # Check confirmation volume
                    confirmation_volume_ok = self._is_reversal_volume_high(candle.volume)
                    self.state.false_sell_confirmation_volume_ok = confirmation_volume_ok
                    self.state.false_sell_confirmation_time = candle.time

                    vol_status = "✓" if confirmation_volume_ok else "✗"
                    self.logger.info(
                        f">>> FALSE SELL CONFIRMATION DETECTED [{self.config.range_config.range_id}] (Conf Vol {vol_status}) <<<",
                        self.symbol,
                    )
                    self.logger.info(f"*** FALSE SELL SIGNAL GENERATED [{self.config.range_config.range_id}] ***", self.symbol, strategy_key=self.key)
                    return self._generate_sell_signal(candle)

        # === FALSE BUY: Check for reversal and confirmation ===
        if self.state.false_buy_qualified:
            breakout_time = self.state.breakout_below_time

            # First check for reversal (price back into range)
            if not self.state.false_buy_reversal_detected:
                # Ensure reversal happens on a later candle than the breakout
                if breakout_time and candle.time <= breakout_time:
                    return None

                if candle.close > candle_ref.low:
                    self.state.false_buy_reversal_detected = True
                    self.state.false_buy_reversal_ok = True
                    self.state.false_buy_reversal_time = candle.time
                    self.logger.info(
                        f">>> FALSE BUY REVERSAL DETECTED [{self.config.range_config.range_id}] <<<",
                        self.symbol, strategy_key=self.key
                    )
                    # Return early to wait for next candle before checking confirmation
                    return None

            # After reversal detected on a previous candle, check for confirmation
            if self.state.false_buy_reversal_detected and not self.state.false_buy_confirmation_detected:
                reversal_time = self.state.false_buy_reversal_time

                # Ensure confirmation happens after the reversal candle
                if reversal_time and candle.time <= reversal_time:
                    return None

                if candle.close > candle_ref.low:
                    self.state.false_buy_confirmation_detected = True
                    self.state.false_buy_confirmation_volume = candle.volume

                    # Check confirmation volume
                    confirmation_volume_ok = self._is_reversal_volume_high(candle.volume)
                    self.state.false_buy_confirmation_volume_ok = confirmation_volume_ok
                    self.state.false_buy_confirmation_time = candle.time

                    vol_status = "✓" if confirmation_volume_ok else "✗"
                    self.logger.info(
                        f">>> FALSE BUY CONFIRMATION DETECTED [{self.config.range_config.range_id}] (Conf Vol {vol_status}) <<<",
                        self.symbol,
                    )

                    self.logger.info(f"*** FALSE BUY SIGNAL GENERATED [{self.config.range_config.range_id}] ***", self.symbol, strategy_key=self.key)
                    return self._generate_buy_signal(candle)

        return None

    def _is_reversal_volume_high(self, reversal_volume: int) -> bool:
        """
        Check if reversal volume is high (tracked but not required).

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
                return False

            avg_volume = self.indicators.calculate_average_volume(
                df['tick_volume'],
                period=20
            )
        else:
            # Use cached average (much faster)
            avg_volume = self.volume_cache.get_average()

        return reversal_volume >= (avg_volume * self.config.min_reversal_volume_multiplier)

    @validation_check(abbreviation="BV", order=1, description="Check breakout volume is low (weak breakout)", required=False)
    def _check_breakout_volume(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if initial breakout had LOW volume (required for fakeout).

        Args:
            signal_data: Dictionary containing:
                - 'signal_direction': int (1 for BUY, -1 for SELL)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        signal_direction = signal_data.get('signal_direction', 0)

        # Get breakout volume from state based on direction
        if signal_direction > 0:  # BUY (failed breakout below)
            breakout_volume = self.state.breakout_below_volume
            volume_ok = self.state.false_buy_volume_ok
        elif signal_direction < 0:  # SELL (failed breakout above)
            breakout_volume = self.state.breakout_above_volume
            volume_ok = self.state.false_sell_volume_ok
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
        # We validate that it was LOW volume (indicating weak breakout)
        direction_str = "BUY" if signal_direction > 0 else "SELL"

        return ValidationResult(
            passed=volume_ok,
            method_name="_check_breakout_volume",
            reason=f"Breakout volume for {direction_str} {'is low' if volume_ok else 'is too high'} (fakeout requires low volume, vol={breakout_volume:.0f})"
        )

    @validation_check(abbreviation="RV", order=2, description="Check reversal back into range")
    def _check_reversal_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if reversal back into range was detected and confirmed.

        Args:
            signal_data: Dictionary containing:
                - 'signal_direction': int (1 for BUY, -1 for SELL)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        signal_direction = signal_data.get('signal_direction', 0)

        # Get reversal status from state based on direction
        if signal_direction > 0:  # BUY (reversal up after failed breakout below)
            reversal_detected = self.state.false_buy_reversal_detected
            reversal_ok = self.state.false_buy_reversal_ok
        elif signal_direction < 0:  # SELL (reversal down after failed breakout above)
            reversal_detected = self.state.false_sell_reversal_detected
            reversal_ok = self.state.false_sell_reversal_ok
        else:
            return ValidationResult(
                passed=False,
                method_name="_check_reversal_confirmation",
                reason="Invalid signal direction"
            )

        direction_str = "BUY" if signal_direction > 0 else "SELL"

        if not reversal_detected:
            return ValidationResult(
                passed=False,
                method_name="_check_reversal_confirmation",
                reason=f"Reversal not detected for {direction_str} signal"
            )

        return ValidationResult(
            passed=reversal_ok,
            method_name="_check_reversal_confirmation",
            reason=f"Reversal {'confirmed' if reversal_ok else 'failed'} for {direction_str} signal"
        )

    @validation_check(abbreviation="RVol", order=3, description="Check reversal volume meets threshold", required=False)
    def _check_reversal_volume(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if reversal/confirmation volume meets configured requirements.

        Args:
            signal_data: Dictionary containing:
                - 'reversal_volume': int - Volume of reversal/confirmation candle
                - 'signal_direction': int (1 for BUY, -1 for SELL)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        signal_direction = signal_data.get('signal_direction', 0)
        reversal_volume = signal_data.get('reversal_volume', 0)

        if reversal_volume <= 0:
            return ValidationResult(
                passed=True,  # Skip check if no volume data
                method_name="_check_reversal_volume",
                reason="No reversal volume data available, skipping"
            )

        # Get reversal volume status from state based on direction
        if signal_direction > 0:  # BUY
            volume_ok = self.state.false_buy_confirmation_volume_ok
        elif signal_direction < 0:  # SELL
            volume_ok = self.state.false_sell_confirmation_volume_ok
        else:
            return ValidationResult(
                passed=True,  # Skip if invalid direction
                method_name="_check_reversal_volume",
                reason="Invalid signal direction, skipping"
            )

        direction_str = "BUY" if signal_direction > 0 else "SELL"

        return ValidationResult(
            passed=volume_ok,
            method_name="_check_reversal_volume",
            reason=f"Reversal volume for {direction_str} {'meets' if volume_ok else 'does not meet'} threshold (vol={reversal_volume:.0f})"
        )

    def _check_divergence_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check for divergence confirmation (optional based on config).

        Args:
            signal_data: Dictionary containing:
                - 'signal_direction': int (1 for BUY, -1 for SELL)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        signal_direction = signal_data.get('signal_direction', 0)

        if signal_direction == 0:
            return ValidationResult(
                passed=True,  # Skip if invalid direction
                method_name="_check_divergence_confirmation",
                reason="Invalid signal direction, skipping"
            )

        # Get candles for divergence detection
        df = self.connector.get_candles(
            self.symbol,
            self.config.range_config.breakout_timeframe,
            count=self.config.divergence_lookback + self.config.rsi_period + 10
        )

        if df is None or len(df) < self.config.divergence_lookback + self.config.rsi_period:
            # If divergence is required, fail; otherwise skip
            if self.config.require_divergence:
                return ValidationResult(
                    passed=False,
                    method_name="_check_divergence_confirmation",
                    reason="Insufficient data for divergence check (required)"
                )
            else:
                return ValidationResult(
                    passed=True,
                    method_name="_check_divergence_confirmation",
                    reason="Insufficient data for divergence check (optional, skipping)"
                )

        direction_str = "BUY" if signal_direction > 0 else "SELL"

        # Check for divergence
        divergence_detected = self._check_divergence(df, direction_str)

        # If divergence is required, it must be detected
        if self.config.require_divergence:
            return ValidationResult(
                passed=divergence_detected,
                method_name="_check_divergence_confirmation",
                reason=f"Divergence {'detected' if divergence_detected else 'NOT detected'} for {direction_str} signal (required)"
            )
        else:
            # If divergence is optional, always pass but log status
            return ValidationResult(
                passed=True,
                method_name="_check_divergence_confirmation",
                reason=f"Divergence {'detected' if divergence_detected else 'NOT detected'} for {direction_str} signal (optional)"
            )

    def _generate_buy_signal(self, candle: CandleData) -> Optional[TradeSignal]:
        """Generate BUY signal (FALSE BUY - reversal up after breakout below)."""
        try:
            # Calculate stop loss using pattern-based position sizer if available
            if isinstance(self.position_sizer, PatternBasedPositionSizer):
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
            else:
                # Fallback to original SL calculation
                symbol_info = self.connector.get_symbol_info(self.symbol)
                if symbol_info is None:
                    self.logger.error(
                        f"Failed to get symbol info for {self.symbol} - cannot calculate stop loss",
                        self.symbol, strategy_key=self.key
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

            # Calculate take profit
            entry_price = candle.close
            sl_distance = abs(entry_price - stop_loss)
            take_profit = entry_price + (sl_distance * self.config.risk_reward_ratio)

            # Calculate lot size from position sizer
            lot_size = self.get_lot_size()

            # Prepare signal data for validation
            signal_data = {
                'signal_direction': 1,  # BUY
                'reversal_volume': candle.volume,
                'current_price': entry_price
            }

            # Validate signal using dynamic validation system
            is_valid, validation_results = self._validate_signal(signal_data)

            if not is_valid:
                failed_checks = [r for r in validation_results if not r.passed]
                for result in failed_checks:
                    self.logger.debug(
                        f"FALSE BUY signal rejected by {result.method_name}: {result.reason}",
                        self.symbol, strategy_key=self.key
                    )
                self.logger.warning("FALSE BUY signal validation failed", self.symbol, strategy_key=self.key)
                self.state.false_buy_rejected = True
                return None
            else:
                self.logger.info("✓ FALSE BUY signal passed all validation filters", self.symbol, strategy_key=self.key)

            # Create signal
            signal = TradeSignal(
                symbol=self.symbol,
                signal_type=PositionType.BUY,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                lot_size=lot_size,
                timestamp=datetime.now(timezone.utc),
                reason=f"Fakeout BUY - {self.config.range_config.range_id}",
                max_spread_percent=0.1,
                comment=self.generate_trade_comment(PositionType.BUY)
            )

            return signal

        except Exception as e:
            self.logger.error(f"Error generating BUY signal: {e}", self.symbol, strategy_key=self.key)
            return None

    def _generate_sell_signal(self, candle: CandleData) -> Optional[TradeSignal]:
        """Generate SELL signal (FALSE SELL - reversal down after breakout above)."""
        try:
            # Calculate stop loss using pattern-based position sizer if available
            if isinstance(self.position_sizer, PatternBasedPositionSizer):
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
            else:
                # Fallback to original SL calculation
                symbol_info = self.connector.get_symbol_info(self.symbol)
                if symbol_info is None:
                    self.logger.error(
                        f"Failed to get symbol info for {self.symbol} - cannot calculate stop loss",
                        self.symbol, strategy_key=self.key
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

            # Calculate take profit
            entry_price = candle.close
            sl_distance = abs(entry_price - stop_loss)
            take_profit = entry_price - (sl_distance * self.config.risk_reward_ratio)

            # Calculate lot size from position sizer
            lot_size = self.get_lot_size()

            # Prepare signal data for validation
            signal_data = {
                'signal_direction': -1,  # SELL
                'reversal_volume': candle.volume,
                'current_price': entry_price
            }

            # Validate signal using dynamic validation system
            is_valid, validation_results = self._validate_signal(signal_data)

            if not is_valid:
                failed_checks = [r for r in validation_results if not r.passed]
                for result in failed_checks:
                    self.logger.debug(
                        f"FALSE SELL signal rejected by {result.method_name}: {result.reason}",
                        self.symbol, strategy_key=self.key
                    )
                self.logger.warning("FALSE SELL signal validation failed", self.symbol, strategy_key=self.key)
                self.state.false_sell_rejected = True
                return None
            else:
                self.logger.info("✓ FALSE SELL signal passed all validation filters", self.symbol, strategy_key=self.key)

            # Create signal
            signal = TradeSignal(
                symbol=self.symbol,
                signal_type=PositionType.SELL,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                lot_size=lot_size,
                timestamp=datetime.now(timezone.utc),
                reason=f"Fakeout SELL - {self.config.range_config.range_id}",
                max_spread_percent=0.1,
                comment=self.generate_trade_comment(PositionType.SELL)
            )

            return signal

        except Exception as e:
            self.logger.error(f"Error generating SELL signal: {e}", self.symbol, strategy_key=self.key)
            return None

    def _check_divergence(self, df: pd.DataFrame, direction: str) -> bool:
        """
        Check for divergence confirmation based on breakout direction.

        For BUY signals (failed breakout below): Check for bullish divergence
        - Price makes lower low, RSI makes higher low

        For SELL signals (failed breakout above): Check for bearish divergence
        - Price makes higher high, RSI makes lower high

        Args:
            df: DataFrame with OHLC data
            direction: Breakout direction ('BUY' or 'SELL')

        Returns:
            True if divergence detected, False otherwise
        """
        if df is None or len(df) < self.config.divergence_lookback + self.config.rsi_period:
            self.logger.debug(
                f"Insufficient data for divergence detection (need {self.config.divergence_lookback + self.config.rsi_period} candles)",
                self.symbol, strategy_key=self.key
            )
            return False

        try:
            if direction == 'BUY':
                # For BUY signal (failed breakout below), check for bullish divergence
                # Price made lower low (breakout below), but RSI should make higher low
                divergence_detected = self.indicators.detect_bullish_rsi_divergence(
                    df,
                    self.config.rsi_period,
                    self.config.divergence_lookback,
                    self.symbol
                )

                if divergence_detected:
                    self.logger.info(
                        "✓ Bullish RSI divergence confirmed for BUY signal",
                        self.symbol, strategy_key=self.key
                    )
                else:
                    self.logger.debug(
                        "No bullish RSI divergence detected",
                        self.symbol, strategy_key=self.key
                    )

                return divergence_detected

            elif direction == 'SELL':
                # For SELL signal (failed breakout above), check for bearish divergence
                # Price made higher high (breakout above), but RSI should make lower high
                divergence_detected = self.indicators.detect_bearish_rsi_divergence(
                    df,
                    self.config.rsi_period,
                    self.config.divergence_lookback,
                    self.symbol
                )

                if divergence_detected:
                    self.logger.info(
                        "✓ Bearish RSI divergence confirmed for SELL signal",
                        self.symbol, strategy_key=self.key
                    )
                else:
                    self.logger.debug(
                        "No bearish RSI divergence detected",
                        self.symbol, strategy_key=self.key
                    )

                return divergence_detected

            else:
                self.logger.warning(
                    f"Unknown breakout direction for divergence check: {direction}",
                    self.symbol, strategy_key=self.key
                )
                return False

        except Exception as e:
            self.logger.error(
                f"Error checking divergence: {e}",
                self.symbol, strategy_key=self.key
            )
            return False

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
            'strategy': 'fakeout',
            'range_id': self.config.range_config.range_id,
            'category': self.category.value if self.category else 'UNKNOWN',
            'last_signal_time': self.last_signal_time.isoformat() if self.last_signal_time else None,
            'breakout_above_detected': self.state.breakout_above_detected,
            'breakout_below_detected': self.state.breakout_below_detected,
            'false_buy_qualified': self.state.false_buy_qualified,
            'false_sell_qualified': self.state.false_sell_qualified,
            'false_buy_reversal_detected': self.state.false_buy_reversal_detected,
            'false_sell_reversal_detected': self.state.false_sell_reversal_detected,
            'false_buy_confirmation_detected': self.state.false_buy_confirmation_detected,
            'false_sell_confirmation_detected': self.state.false_sell_confirmation_detected,
            'reference_candle': {
                'high': self.current_reference_candle.high if self.current_reference_candle else None,
                'low': self.current_reference_candle.low if self.current_reference_candle else None,
                'time': self.current_reference_candle.time.isoformat() if self.current_reference_candle else None
            } if self.current_reference_candle else None,
            'config': {
                'range_timeframe': self.config.range_config.reference_timeframe,
                'confirmation_timeframe': self.config.range_config.breakout_timeframe,
                'check_divergence': self.config.check_divergence,
                'require_divergence': self.config.require_divergence,
                'risk_reward_ratio': self.config.risk_reward_ratio
            }
        }

    def shutdown(self) -> None:
        """Cleanup and shutdown the strategy."""
        self.logger.info(
            f"Fakeout strategy shutdown for {self.symbol} [{self.config.range_config.range_id}]",
            self.symbol, strategy_key=self.key
        )

