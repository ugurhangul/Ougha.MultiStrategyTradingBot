"""
HFT Momentum Strategy

High-frequency trading strategy that combines:
- Tick-level momentum detection (consecutive tick movements)
- Multi-layer signal validation (momentum, volume, volatility, trend, spread)
- Flexible position sizing (can use fixed, martingale, or other position sizers)
- Dynamic stop loss based on symbol category and ATR

This is a complementary strategy to the existing 4H/15M breakout strategies,
operating on tick-level data for high-frequency scalping opportunities.

Refactored to use plugin-based architecture with shared utilities and position sizing plugins.
"""
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timezone
import MetaTrader5 as mt5
import numpy as np
import talib

from src.models.data_models import (
    TradeSignal, PositionType, SymbolCategory, SymbolParameters
)
from src.core.mt5_connector import MT5Connector
from src.execution.order_manager import OrderManager
from src.execution.trade_manager import TradeManager
from src.indicators.technical_indicators import TechnicalIndicators
from src.indicators.tick_momentum_indicator import TickMomentumIndicator
from src.indicators.atr_average_indicator import ATRAverageIndicator
from src.indicators.spread_indicator import SpreadIndicator
from src.risk.risk_manager import RiskManager
from src.strategy.base_strategy import BaseStrategy, ValidationResult
from src.strategy.strategy_factory import register_strategy
from src.strategy.validation_decorator import validation_check, auto_register_validations
from src.strategy.symbol_performance_persistence import SymbolPerformancePersistence
from src.config.configs import HFTMomentumConfig
from src.config.strategies import MartingaleType
from src.utils.strategy import (
    SymbolCategoryUtils, StopLossCalculator,
    ValidationThresholdsCalculator, SignalValidationHelpers
)
from src.utils.logger import get_logger


class TickData:
    """Tick data structure"""

    def __init__(self, time: datetime, bid: float, ask: float, volume: int):
        self.time = time
        self.bid = bid
        self.ask = ask
        self.volume = volume
        self.mid = (bid + ask) / 2.0


@register_strategy(
    "hft_momentum",
    description="HFT tick momentum strategy with flexible position sizing",
    key="hft",
    enabled_by_default=False,
    requires_tick_data=True
)
class HFTMomentumStrategy(BaseStrategy):
    """
    HFT Momentum Strategy

    Detects tick-level momentum and validates signals through multiple filters
    before executing trades with flexible position sizing (fixed, martingale, etc.).

    Refactored to use BaseStrategy interface, shared utilities, and position sizing plugins.
    """

    def __init__(self, symbol: str, connector: MT5Connector,
                 order_manager: OrderManager, risk_manager: RiskManager,
                 trade_manager: TradeManager, indicators: TechnicalIndicators,
                 position_sizer=None,
                 symbol_persistence: Optional[SymbolPerformancePersistence] = None,
                 config: Optional[HFTMomentumConfig] = None,
                 **kwargs):
        """
        Initialize HFT Momentum strategy.

        Args:
            symbol: Symbol name
            connector: MT5 connector instance
            order_manager: Order manager instance
            risk_manager: Risk manager instance
            trade_manager: Trade manager instance
            indicators: Technical indicators instance
            position_sizer: Position sizing plugin (injected by factory)
            symbol_persistence: Symbol performance persistence (optional)
            config: Strategy configuration (loads from env if None)
            **kwargs: Additional parameters
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

        # Strategy-specific configuration
        self.config = config or HFTMomentumConfig.from_env()
        self.symbol_persistence = symbol_persistence

        # Symbol parameters (will be set in initialize())
        self.symbol_params: Optional[Dict[str, Any]] = None

        # Cooldown tracking
        self.last_trade_time: Optional[datetime] = None
        self.last_signal_time: Optional[datetime] = None

        # Tick buffer for momentum detection
        self.tick_buffer: List[TickData] = []
        self.max_tick_buffer_size: int = max(
            self.config.tick_momentum_count,
            self.config.volume_lookback,
            self.config.spread_lookback
        ) + 10  # Extra buffer for safety

        # Validation thresholds (will be set in initialize())
        self.validation_thresholds = None

        # Initialize indicator instances
        self.tick_momentum_indicator = TickMomentumIndicator()
        self.atr_avg_indicator = ATRAverageIndicator()
        self.spread_indicator = SpreadIndicator()

        # All validations must pass (AND logic)
        self._validation_mode = "all"
        self.key = "HFT"  # Format: "HFT" (no range_id)

        # Auto-register validation methods using decorator
        auto_register_validations(self)

    def initialize(self) -> bool:
        """
        Initialize the strategy.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Detect symbol category using shared utility
            symbol_info = self.connector.get_symbol_info(self.symbol)
            if symbol_info is None:
                self.logger.error(f"Failed to get symbol info for {self.symbol}")
                return False

            mt5_category = symbol_info.get('category', '')
            self.category = SymbolCategoryUtils.detect_category(self.symbol, mt5_category)

            # Store symbol info for later use (no persistence needed - can be retrieved from MT5)
            self.symbol_params = {
                'symbol': self.symbol,
                'category': self.category,
                'point': symbol_info['point'],
                'digits': symbol_info['digits'],
                'min_lot': symbol_info['min_lot'],
                'max_lot': symbol_info['max_lot'],
                'lot_step': symbol_info['lot_step']
            }

            # Get validation thresholds from shared utility
            self.validation_thresholds = ValidationThresholdsCalculator.get_thresholds(self.category)

            # Apply auto-optimization if enabled
            if self.config.use_auto_optimization:
                self._apply_auto_optimization()

            # Initialize position sizer with base lot size from risk manager
            if self.position_sizer is not None:
                # Calculate initial lot size based on risk
                # Get current price for initial calculation
                current_price = self.connector.get_current_price(self.symbol)
                if current_price is None:
                    self.logger.error(f"Failed to get current price for {self.symbol}")
                    return False

                # Calculate a default stop loss for initialization (100 points)
                point = symbol_info['point']
                default_sl = current_price - (100 * point)  # Assume BUY for initialization

                initial_lot = self.risk_manager.calculate_lot_size(
                    symbol=self.symbol,
                    entry_price=current_price,
                    stop_loss=default_sl
                )
                self.position_sizer.initialize(initial_lot)
                self.logger.info(
                    f"Position sizer initialized: {self.position_sizer.get_name()} with {initial_lot:.2f} lots",
                    self.symbol
                )

            self.is_initialized = True
            self.logger.info(
                f"HFT Momentum strategy initialized for {self.symbol} "
                f"(Category: {self.category.value}, Tick Count: {self.config.tick_momentum_count})"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize HFT Momentum strategy: {e}")
            return False

    def _apply_auto_optimization(self):
        """
        Apply symbol-specific parameter optimization based on category.

        Uses shared ValidationThresholdsCalculator for consistency.
        """
        # Get symbol info for spread calculations
        symbol_info = self.connector.get_symbol_info(self.symbol)
        if symbol_info is None:
            self.logger.warning(
                f"Could not get symbol info for auto-optimization, using defaults",
                self.symbol, strategy_key=self.key
            )
            return

        point = symbol_info['point']

        # Calculate average spread
        avg_spread = self._calculate_average_spread()
        if avg_spread is None:
            avg_spread = self.connector.get_spread(self.symbol) or 10.0

        # Use shared validation thresholds
        thresholds = self.validation_thresholds

        # Calculate momentum threshold using shared utility
        self.config.min_momentum_strength = ValidationThresholdsCalculator.calculate_momentum_threshold(
            self.category, avg_spread, point
        )

        # Apply category-specific thresholds from shared utility
        self.config.min_volume_multiplier = thresholds.min_volume_multiplier
        self.config.min_atr_multiplier = thresholds.min_atr_multiplier
        self.config.max_atr_multiplier = thresholds.max_atr_multiplier
        self.config.trend_ema_period = thresholds.trend_ema_period
        self.config.max_spread_multiplier = thresholds.max_spread_multiplier

        self.logger.info(
            f"Auto-optimization applied for {self.category.value}: "
            f"min_momentum={self.config.min_momentum_strength:.6f}, "
            f"volume_mult={self.config.min_volume_multiplier:.1f}, "
            f"atr_range=[{self.config.min_atr_multiplier:.1f}, {self.config.max_atr_multiplier:.1f}]",
            self.symbol, strategy_key=self.key
        )

    def _calculate_average_spread(self) -> Optional[float]:
        """Calculate average spread over recent ticks"""
        if len(self.tick_buffer) < self.config.spread_lookback:
            return None

        symbol_info = self.connector.get_symbol_info(self.symbol)
        if symbol_info is None:
            return None

        # Use SpreadIndicator for calculation
        return self.spread_indicator.calculate_average_spread_from_ticks(
            ticks=self.tick_buffer,
            point=symbol_info['point'],
            lookback=self.config.spread_lookback
        )

    def on_tick(self) -> Optional[TradeSignal]:
        """
        Process tick event and check for trade signals.

        Returns:
            TradeSignal if signal detected, None otherwise
        """
        # Check cooldown
        if not self._check_cooldown():
            return None

        # Check if position sizer is disabled (e.g., due to consecutive loss limit)
        if self.position_sizer is not None and not self.position_sizer.is_enabled():
            return None

        # Update tick buffer
        if not self._update_tick_buffer():
            return None

        # Need minimum ticks for analysis
        if len(self.tick_buffer) < self.config.tick_momentum_count:
            return None

        # Detect HFT momentum signal
        signal_direction = self._detect_tick_momentum()

        if signal_direction == 0:
            return None  # No signal

        # Validate signal through multi-layer filters using dynamic validation system
        recent_ticks = self.tick_buffer[-self.config.tick_momentum_count:]

        signal_data = {
            'signal_direction': signal_direction,
            'recent_ticks': recent_ticks,
            'current_price': self.tick_buffer[-1].mid if self.tick_buffer else None
        }

        # Use the dynamic validation system from BaseStrategy
        is_valid, validation_results = self._validate_signal(signal_data)

        # Log detailed results if validation failed
        if not is_valid:
            failed_checks = [r for r in validation_results if not r.passed]
            for result in failed_checks:
                self.logger.debug(
                    f"Signal rejected by {result.method_name}: {result.reason}",
                    self.symbol, strategy_key=self.key
                )
            return None
        else:
            self.logger.info("✓ Signal passed all validation filters", self.symbol, strategy_key=self.key)
        return self._generate_signal(signal_direction)

    def _check_cooldown(self) -> bool:
        """Check if cooldown period has elapsed"""
        if self.last_trade_time is None:
            return True

        elapsed = (datetime.now(timezone.utc) - self.last_trade_time).total_seconds()
        return elapsed >= self.config.trade_cooldown_seconds

    def _update_tick_buffer(self) -> bool:
        """Update tick buffer with latest tick data"""
        try:
            # Get latest tick
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                return False

            # Create TickData object
            tick_data = TickData(
                time=datetime.fromtimestamp(tick.time, tz=timezone.utc),
                bid=tick.bid,
                ask=tick.ask,
                volume=tick.volume
            )

            # Add to buffer
            self.tick_buffer.append(tick_data)

            # Trim buffer if too large
            if len(self.tick_buffer) > self.max_tick_buffer_size:
                self.tick_buffer = self.tick_buffer[-self.max_tick_buffer_size:]

            return True

        except Exception as e:
            self.logger.error(f"Error updating tick buffer: {e}", self.symbol, strategy_key=self.key)
            return False

    def _detect_tick_momentum(self) -> int:
        """
        Detect tick-level momentum (HFT signal).

        Returns:
            1 for BUY signal (upward momentum)
            -1 for SELL signal (downward momentum)
            0 for no signal
        """
        # Get last N ticks
        recent_ticks = self.tick_buffer[-self.config.tick_momentum_count:]

        if len(recent_ticks) < self.config.tick_momentum_count:
            return 0

        # Use TickMomentumIndicator for consecutive movement detection
        is_upward = self.tick_momentum_indicator.detect_consecutive_upward_movement(
            ticks=recent_ticks,
            min_count=self.config.tick_momentum_count
        )

        is_downward = self.tick_momentum_indicator.detect_consecutive_downward_movement(
            ticks=recent_ticks,
            min_count=self.config.tick_momentum_count
        )

        if is_upward:
            self.logger.debug(
                f"Upward tick momentum detected ({self.config.tick_momentum_count} consecutive rising ticks)",
                self.symbol
            )
            return 1  # BUY signal
        elif is_downward:
            self.logger.debug(
                f"Downward tick momentum detected ({self.config.tick_momentum_count} consecutive falling ticks)",
                self.symbol
            )
            return -1  # SELL signal

        return 0  # No clear momentum

    @validation_check(abbreviation="M", order=1, description="Check momentum strength")
    def _check_momentum_strength(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if momentum strength exceeds minimum threshold.

        CRITICAL FIX: Uses cumulative tick-to-tick changes (aligned with MQL5)
        instead of simple first-to-last difference.

        Args:
            signal_data: Dictionary containing:
                - 'recent_ticks': List[TickData]
                - 'signal_direction': int (1 for BUY, -1 for SELL)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        ticks = signal_data.get('recent_ticks', [])
        direction = signal_data.get('signal_direction', 0)

        if len(ticks) < 2:
            return ValidationResult(
                passed=False,
                method_name="_check_momentum_strength",
                reason="Insufficient tick data (need at least 2 ticks)"
            )

        # Use TickMomentumIndicator for cumulative momentum strength check
        passed = self.tick_momentum_indicator.check_momentum_strength(
            ticks=ticks,
            direction=direction,
            min_strength=self.config.min_momentum_strength
        )

        return ValidationResult(
            passed=passed,
            method_name="_check_momentum_strength",
            reason="Momentum strength sufficient" if passed else f"Momentum strength below threshold ({self.config.min_momentum_strength})"
        )

    @validation_check(abbreviation="V", order=2, description="Check volume confirmation")
    def _check_volume_confirmation(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if recent volume exceeds average using M1 candle tick_volume data.

        Uses M1 candle tick_volume instead of tick-level volume because:
        - Candle tick_volume represents number of price changes during that minute
        - This data is always available and non-zero for active symbols (unlike tick.volume)
        - Provides a more stable measure of market activity
        - Works reliably for Forex/CFD symbols like XAUUSD

        Args:
            signal_data: Dictionary containing:
                - 'recent_ticks': List[TickData] (not used, kept for compatibility)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        # Fetch M1 candles for volume analysis
        # We need lookback + a few extra candles to ensure we have enough data
        candle_count = self.config.volume_lookback + 5
        df = self.connector.get_candles(self.symbol, "M1", count=candle_count)

        if df is None or len(df) < self.config.volume_lookback:
            return ValidationResult(
                passed=True,
                method_name="_check_volume_confirmation",
                reason=f"Not enough M1 candle data for volume check (need {self.config.volume_lookback}, got {len(df) if df is not None else 0}), skipping"
            )

        # Calculate average volume over lookback period using tick_volume from candles
        # Use the most recent N candles for lookback
        lookback_candles = df.tail(self.config.volume_lookback)
        avg_volume = lookback_candles['tick_volume'].mean()

        # Calculate recent volume from the most recent candle(s)
        # Use the last 1-3 candles as "recent" activity
        recent_candle_count = min(3, len(df))
        recent_candles = df.tail(recent_candle_count)
        recent_volume = recent_candles['tick_volume'].mean()

        # Check for zero average volume (should not happen for active symbols, but safety check)
        if avg_volume <= 0:
            return ValidationResult(
                passed=True,
                method_name="_check_volume_confirmation",
                reason=f"Average M1 tick_volume is zero (avg={avg_volume:.1f}), skipping volume check"
            )

        # Use shared validation helper
        passed = SignalValidationHelpers.check_volume_confirmation(
            recent_volume, avg_volume, self.config.min_volume_multiplier
        )

        volume_ratio = recent_volume / avg_volume

        return ValidationResult(
            passed=passed,
            method_name="_check_volume_confirmation",
            reason=f"M1 volume ratio {volume_ratio:.2f} {'≥' if passed else '<'} {self.config.min_volume_multiplier} (recent={recent_volume:.0f}, avg={avg_volume:.0f})"
        )

    @validation_check(abbreviation="A", order=3, description="Check volatility (ATR) filter")
    def _check_volatility_filter(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if current volatility (ATR) is within acceptable range.

        Uses shared SignalValidationHelpers for consistency.

        Args:
            signal_data: Dictionary (not used in this method, but required for signature)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        # Check if volatility filter is enabled
        if not self.config.enable_volatility_filter:
            return ValidationResult(
                passed=True,
                method_name="_check_volatility_filter",
                reason="Volatility filter disabled in config"
            )

        try:
            # Get candle data for ATR calculation
            df = self.connector.get_candles(
                self.symbol,
                self.config.atr_timeframe,
                count=self.config.atr_period + 50
            )

            if df is None or len(df) < self.config.atr_period + 1:
                return ValidationResult(
                    passed=True,
                    method_name="_check_volatility_filter",
                    reason="Not enough data for ATR calculation, skipping"
                )

            # Calculate ATR
            current_atr = self.indicators.calculate_atr(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                period=self.config.atr_period
            )

            if current_atr is None:
                return ValidationResult(
                    passed=True,
                    method_name="_check_volatility_filter",
                    reason="ATR calculation failed, skipping"
                )

            # Use ATRAverageIndicator for average ATR calculation
            avg_atr = self.atr_avg_indicator.calculate_average_atr(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                atr_period=self.config.atr_period,
                average_period=20
            )

            # Fallback to current ATR if average calculation fails
            if avg_atr is None:
                avg_atr = current_atr

            # Use shared validation helper
            passed = SignalValidationHelpers.check_atr_filter(
                current_atr, avg_atr,
                self.config.min_atr_multiplier,
                self.config.max_atr_multiplier
            )

            atr_ratio = current_atr / avg_atr if avg_atr > 0 else 0
            return ValidationResult(
                passed=passed,
                method_name="_check_volatility_filter",
                reason=f"ATR ratio {atr_ratio:.2f} {'within' if passed else 'outside'} range [{self.config.min_atr_multiplier}, {self.config.max_atr_multiplier}]"
            )

        except Exception as e:
            self.logger.error(f"Error checking volatility filter: {e}", self.symbol, strategy_key=self.key)
            return ValidationResult(
                passed=True,
                method_name="_check_volatility_filter",
                reason=f"Exception occurred: {str(e)}, skipping"
            )

    @validation_check(abbreviation="T", order=4, description="Check trend alignment")
    def _check_trend_alignment(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if signal aligns with higher timeframe trend (EMA).

        Uses shared SignalValidationHelpers for consistency.

        Args:
            signal_data: Dictionary containing:
                - 'signal_direction': int (1 for BUY, -1 for SELL)
                - 'current_price': float

        Returns:
            ValidationResult with pass/fail status and reason
        """
        # Check if trend filter is enabled
        if not self.config.enable_trend_filter:
            return ValidationResult(
                passed=True,
                method_name="_check_trend_alignment",
                reason="Trend filter disabled in config"
            )

        signal_direction = signal_data.get('signal_direction', 0)
        current_price = signal_data.get('current_price')

        try:
            # Get candle data for EMA calculation
            df = self.connector.get_candles(
                self.symbol,
                self.config.trend_ema_timeframe,
                count=self.config.trend_ema_period + 50
            )

            if df is None or len(df) < self.config.trend_ema_period:
                return ValidationResult(
                    passed=True,
                    method_name="_check_trend_alignment",
                    reason="Not enough data for EMA calculation, skipping"
                )

            # Calculate EMA using talib
            ema_values = talib.EMA(df['close'].values, timeperiod=self.config.trend_ema_period)

            if ema_values is None or len(ema_values) == 0:
                return ValidationResult(
                    passed=True,
                    method_name="_check_trend_alignment",
                    reason="EMA calculation failed, skipping"
                )

            current_ema = ema_values[-1]

            # Check for NaN
            if np.isnan(current_ema):
                return ValidationResult(
                    passed=True,
                    method_name="_check_trend_alignment",
                    reason="Invalid EMA value (NaN), skipping"
                )

            if current_price is None:
                current_price = self.tick_buffer[-1].mid if self.tick_buffer else None

            if current_price is None:
                return ValidationResult(
                    passed=True,
                    method_name="_check_trend_alignment",
                    reason="No current price available, skipping"
                )

            is_buy_signal = signal_direction > 0

            # Use shared validation helper
            passed = SignalValidationHelpers.check_trend_alignment(
                current_price, current_ema, is_buy_signal
            )

            direction_str = "BUY" if is_buy_signal else "SELL"
            alignment = "above" if current_price > current_ema else "below"
            return ValidationResult(
                passed=passed,
                method_name="_check_trend_alignment",
                reason=f"{direction_str} signal with price {alignment} EMA ({current_price:.5f} vs {current_ema:.5f})"
            )

        except Exception as e:
            self.logger.error(f"Error checking trend alignment: {e}", self.symbol, strategy_key=self.key)
            return ValidationResult(
                passed=True,
                method_name="_check_trend_alignment",
                reason=f"Exception occurred: {str(e)}, skipping"
            )

    @validation_check(abbreviation="S", order=5, description="Check spread filter")
    def _check_spread_filter(self, signal_data: Dict[str, Any]) -> ValidationResult:
        """
        Check if current spread is within acceptable limits.

        Uses shared SignalValidationHelpers for consistency.

        Args:
            signal_data: Dictionary (not used in this method, but required for signature)

        Returns:
            ValidationResult with pass/fail status and reason
        """
        # Calculate average spread
        avg_spread = self._calculate_average_spread()
        if avg_spread is None:
            return ValidationResult(
                passed=True,
                method_name="_check_spread_filter",
                reason="Not enough data for spread calculation, skipping"
            )

        # Get current spread
        current_spread = self.connector.get_spread(self.symbol)
        if current_spread is None:
            return ValidationResult(
                passed=True,
                method_name="_check_spread_filter",
                reason="Cannot get current spread, skipping"
            )

        # Use shared validation helper
        passed = SignalValidationHelpers.check_spread_filter(
            current_spread, avg_spread, self.config.max_spread_multiplier
        )

        spread_ratio = current_spread / avg_spread if avg_spread > 0 else 0
        max_allowed = avg_spread * self.config.max_spread_multiplier
        return ValidationResult(
            passed=passed,
            method_name="_check_spread_filter",
            reason=f"Spread {current_spread:.1f} {'≤' if passed else '>'} max allowed {max_allowed:.1f} (ratio: {spread_ratio:.2f})"
        )

    def _generate_signal(self, direction: int) -> TradeSignal:
        """
        Generate trade signal with dynamic stop loss and take profit.

        Args:
            direction: 1 for BUY, -1 for SELL

        Returns:
            TradeSignal object
        """
        # Get current price
        current_tick = self.tick_buffer[-1]

        if direction > 0:  # BUY
            entry_price = current_tick.ask
            signal_type = PositionType.BUY
        else:  # SELL
            entry_price = current_tick.bid
            signal_type = PositionType.SELL

        # Calculate dynamic stop loss
        stop_loss = self._calculate_dynamic_stop_loss(entry_price, signal_type)

        # Calculate take profit based on R:R ratio
        sl_distance = abs(entry_price - stop_loss)
        tp_distance = sl_distance * self.config.risk_reward_ratio

        if signal_type == PositionType.BUY:
            take_profit = entry_price + tp_distance
        else:
            take_profit = entry_price - tp_distance

        # Update last trade time and signal time
        current_time = datetime.now(timezone.utc)
        self.last_trade_time = current_time
        self.last_signal_time = current_time

        # Create signal
        signal = TradeSignal(
            symbol=self.symbol,
            signal_type=signal_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=self.get_lot_size(),  # Get lot size from position sizer
            timestamp=datetime.now(timezone.utc),
            reason=f"HFT Momentum - {self.config.tick_momentum_count} tick momentum",
            max_spread_percent=3.0,  # Will be validated by spread check
            comment=self.generate_trade_comment(signal_type.value)
        )

        can_open, reason = self.risk_manager.can_open_new_position(
            magic_number=self.order_manager.magic_number,
            symbol=self.symbol,
            position_type=signal.signal_type,
            all_confirmations_met=False,  # TODO: Extract from signal if needed
            strategy_type=self.key,
            range_id=None
        )
        if not can_open:
            self.logger.warning(f"Position limit check failed: {reason}", self.symbol, strategy_key=self.key)
            return None


        self.logger.info("*** HFT MOMENTUM SIGNAL GENERATED ***", self.symbol, strategy_key=self.key)


        return signal

    def _calculate_dynamic_stop_loss(self, entry_price: float,
                                     signal_type: PositionType) -> float:
        """
        Calculate dynamic stop loss based on symbol category and ATR.

        REFACTORED: Uses shared StopLossCalculator with corrected MQL5-aligned values.

        Args:
            entry_price: Entry price
            signal_type: BUY or SELL

        Returns:
            Stop loss price
        """
        # Get symbol info for point value
        symbol_info = self.connector.get_symbol_info(self.symbol)
        if symbol_info is None:
            return 0.0

        point = symbol_info['point']

        # Get current ATR if ATR multiplier is enabled
        current_atr = None
        if self.config.use_atr_multiplier:
            try:
                # Get candle data for ATR calculation
                df = self.connector.get_candles(
                    self.symbol,
                    self.config.atr_timeframe,
                    count=self.config.atr_period + 50
                )

                if df is not None and len(df) >= self.config.atr_period + 1:
                    # Calculate ATR
                    current_atr = self.indicators.calculate_atr(
                        high=df['high'],
                        low=df['low'],
                        close=df['close'],
                        period=self.config.atr_period
                    )
            except Exception as e:
                self.logger.error(f"Error getting ATR for SL calculation: {e}", self.symbol, strategy_key=self.key)

        # Use shared StopLossCalculator to get SL distance in points
        sl_points = StopLossCalculator.calculate_dynamic_stop_loss(
            category=self.category,
            current_atr=current_atr,
            point=point,
            use_atr=self.config.use_atr_multiplier,
            custom_atr_multiplier=None
        )

        # Convert points to price
        sl_distance = sl_points * point

        # Calculate stop loss price based on direction
        if signal_type == PositionType.BUY:
            stop_loss = entry_price - sl_distance
        else:
            stop_loss = entry_price + sl_distance

        # Normalize to symbol digits
        digits = symbol_info['digits']
        stop_loss = round(stop_loss, digits)

        return stop_loss

    def on_position_closed(self, symbol: str, profit: float,
                           volume: float, comment: str) -> None:
        """
        Handle position closure event (BaseStrategy interface).

        Args:
            symbol: Symbol of closed position
            profit: Profit/loss of closed position
            volume: Volume of closed position
            comment: Comment of closed position
        """
        # Only process if it's for this symbol
        if symbol != self.symbol:
            return

        # Delegate to internal method
        if self.position_sizer is not None:
            self.position_sizer.on_trade_closed(profit, volume)

            # Log position sizer state
            state = self.position_sizer.get_state()
            self.logger.info(
                f"Position sizer updated: {state.get('type', 'unknown')} | "
                f"Current lot: {state.get('current_lot_size', 0):.2f} | "
                f"Enabled: {state.get('is_enabled', False)}",
                self.symbol
            )

    def reset_position_sizer(self):
        """Reset position sizer state (called on new day or manual reset)"""
        if self.position_sizer is not None:
            self.position_sizer.reset()
            self.logger.info("Position sizer reset", self.symbol, strategy_key=self.key)

    def get_status(self) -> Dict[str, Any]:
        """
        Get current strategy status (BaseStrategy interface).

        Returns:
            Dictionary with status information
        """
        # Get position sizer state
        position_sizer_state = {}
        if self.position_sizer is not None:
            position_sizer_state = self.position_sizer.get_state()

        return {
            'is_initialized': self.is_initialized,
            'symbol': self.symbol,
            'category': self.category.value if self.category else 'UNKNOWN',
            'last_signal_time': self.last_signal_time.isoformat() if self.last_signal_time else None,
            'position_sizer': position_sizer_state,
            'tick_buffer_size': len(self.tick_buffer),
            'config': {
                'tick_momentum_count': self.config.tick_momentum_count,
                'min_momentum_strength': self.config.min_momentum_strength,
                'min_volume_multiplier': self.config.min_volume_multiplier,
                'atr_range': f"[{self.config.min_atr_multiplier}, {self.config.max_atr_multiplier}]",
                'max_spread_multiplier': self.config.max_spread_multiplier
            }
        }

    def shutdown(self) -> None:
        """
        Cleanup and shutdown the strategy (BaseStrategy interface).
        """
        # No persistence needed for symbol parameters (can be retrieved from MT5)
        self.logger.info(f"HFT Momentum strategy shutdown for {self.symbol}")
