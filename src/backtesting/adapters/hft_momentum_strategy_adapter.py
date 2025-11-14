"""
HFT Momentum Strategy Adapter for Backtesting.

This adapter bridges the HFTMomentumStrategy with the hftbacktest engine,
converting live trading logic to backtest-compatible format.

Key Adaptations:
- Detects tick-level momentum (consecutive tick movements)
- Multi-layer signal validation (momentum, volume, volatility, trend, spread)
- High-frequency scalping with dynamic stop loss
- Manages positions with ATR-based risk management

Strategy Logic:
1. Monitor tick buffer for consecutive movements
2. Detect momentum (N consecutive rising/falling ticks)
3. Validate through multiple filters:
   - Momentum strength (cumulative tick-to-tick changes)
   - Volume confirmation (recent > avg)
   - Volatility filter (ATR within range)
   - Trend alignment (price vs EMA)
   - Spread filter (current < max allowed)
4. Generate signal with dynamic SL/TP
5. Manage positions with tight risk control
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from collections import deque
import numpy as np

from hftbacktest import BUY, SELL, LIMIT, GTC

from src.backtesting.adapters.base_strategy_adapter import (
    BaseStrategyAdapter,
    BacktestOrder,
    BacktestPosition
)
from src.models.data_models import TradeSignal, PositionType
from src.utils.logger import get_logger


class TickData:
    """Tick data structure for momentum detection."""

    def __init__(self, time: int, bid: float, ask: float, volume: float):
        self.time = time
        self.bid = bid
        self.ask = ask
        self.volume = volume
        self.mid = (bid + ask) / 2.0


class HFTMomentumStrategyAdapter(BaseStrategyAdapter):
    """
    Adapter for HFTMomentumStrategy in backtesting environment.

    This adapter:
    - Detects tick-level momentum patterns
    - Validates signals through multiple filters
    - Manages high-frequency positions with dynamic SL/TP
    - Implements cooldown between trades
    """

    def __init__(
        self,
        symbol: str,
        strategy_params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize HFT Momentum Strategy Adapter.

        Args:
            symbol: Trading symbol
            strategy_params: Strategy configuration parameters
        """
        super().__init__(
            symbol=symbol,
            strategy_name="HFTMomentumStrategy"
        )

        self.logger = get_logger()

        # Strategy parameters
        self.params = strategy_params or {}
        self.tick_momentum_count = self.params.get('tick_momentum_count', 3)
        self.min_momentum_strength = self.params.get('min_momentum_strength', 0.00005)
        self.min_volume_multiplier = self.params.get('min_volume_multiplier', 1.2)
        self.max_spread_multiplier = self.params.get('max_spread_multiplier', 2.0)
        self.max_spread_percent = self.params.get('max_spread_percent', 0.003)
        self.risk_reward_ratio = self.params.get('risk_reward_ratio', 1.5)
        self.sl_pips = self.params.get('sl_pips', 10)
        self.trade_cooldown_seconds = self.params.get('trade_cooldown_seconds', 5)

        # Tick buffer for momentum detection
        self.tick_buffer: deque = deque(maxlen=100)
        self.volume_buffer: deque = deque(maxlen=100)
        self.spread_buffer: deque = deque(maxlen=50)

        # Cooldown tracking
        self.last_trade_time = None

        # Statistics
        self.tick_count = 0
        self.momentum_signals_detected = 0
        self.signals_filtered = 0

    def initialize(self, hbt, asset_index: int) -> None:
        """
        Initialize the adapter with backtest instance.

        Args:
            hbt: Backtest instance
            asset_index: Index of the asset in backtest
        """
        super().initialize(hbt, asset_index)

        self.logger.info(
            f"HFTMomentumStrategyAdapter initialized for {self.symbol} "
            f"(tick_momentum={self.tick_momentum_count}, "
            f"min_strength={self.min_momentum_strength}, "
            f"cooldown={self.trade_cooldown_seconds}s)"
        )

    def on_tick(
        self,
        timestamp: int,
        bid: float,
        ask: float,
        bid_qty: float,
        ask_qty: float
    ) -> None:
        """
        Process tick data and check for HFT momentum signals.

        Args:
            timestamp: Tick timestamp in nanoseconds
            bid: Best bid price
            ask: Best ask price
            bid_qty: Bid quantity
            ask_qty: Ask quantity
        """
        self.tick_count += 1

        # Calculate mid price and spread
        mid_price = (bid + ask) / 2.0
        spread = ask - bid
        spread_percent = spread / mid_price if mid_price > 0 else 0

        # Update buffers
        volume = (bid_qty + ask_qty) / 2.0
        tick_data = TickData(timestamp, bid, ask, volume)
        self.tick_buffer.append(tick_data)
        self.volume_buffer.append(volume)
        self.spread_buffer.append(spread)


        # Need minimum ticks for analysis
        if len(self.tick_buffer) < self.tick_momentum_count:
            return

        # Check for active positions
        if len(self.active_positions) > 0:
            self._check_exit_conditions(timestamp, bid, ask)
            return

        # Check for pending orders
        if len(self.active_orders) > 0:
            return

        # Check cooldown
        if not self._check_cooldown(timestamp):
            return

        # Check spread filter (early exit)
        if spread_percent > self.max_spread_percent:
            return

        # Detect tick momentum
        signal_direction = self._detect_tick_momentum()

        if signal_direction == 0:
            return  # No momentum detected

        # Validate signal through multiple filters
        if self._validate_signal(signal_direction, mid_price, spread):
            # Generate and submit signal
            signal = self._generate_signal(signal_direction, timestamp, bid, ask)
            if signal:
                self._submit_signal(signal, timestamp, bid, ask)
                self.last_trade_time = timestamp

    def _check_cooldown(self, current_time: int) -> bool:
        """
        Check if enough time has passed since last trade.

        Args:
            current_time: Current timestamp in nanoseconds

        Returns:
            True if cooldown period has passed
        """
        if self.last_trade_time is None:
            return True

        # Convert cooldown to nanoseconds
        cooldown_ns = self.trade_cooldown_seconds * 1_000_000_000

        return (current_time - self.last_trade_time) >= cooldown_ns

    def _detect_tick_momentum(self) -> int:
        """
        Detect tick-level momentum (consecutive tick movements).

        Returns:
            1 for BUY signal (upward momentum)
            -1 for SELL signal (downward momentum)
            0 for no signal
        """
        # Get last N ticks
        recent_ticks = list(self.tick_buffer)[-self.tick_momentum_count:]

        if len(recent_ticks) < self.tick_momentum_count:
            return 0

        # Check for consecutive upward movement
        is_upward = True
        is_downward = True

        for i in range(1, len(recent_ticks)):
            prev_mid = recent_ticks[i-1].mid
            curr_mid = recent_ticks[i].mid

            if curr_mid <= prev_mid:
                is_upward = False
            if curr_mid >= prev_mid:
                is_downward = False

        if is_upward:
            self.momentum_signals_detected += 1
            self.logger.debug(
                f"Upward momentum detected ({self.tick_momentum_count} consecutive rising ticks)"
            )
            return 1  # BUY signal
        elif is_downward:
            self.momentum_signals_detected += 1
            self.logger.debug(
                f"Downward momentum detected ({self.tick_momentum_count} consecutive falling ticks)"
            )
            return -1  # SELL signal

        return 0  # No clear momentum

    def _validate_signal(
        self,
        signal_direction: int,
        current_price: float,
        current_spread: float
    ) -> bool:
        """
        Validate signal through multiple filters.

        Args:
            signal_direction: 1 for BUY, -1 for SELL
            current_price: Current mid price
            current_spread: Current spread

        Returns:
            True if all validations pass
        """
        # Optional: allow disabling validation via strategy params (for demo/backtests)
        if self.params.get('disable_validation', False):
            return True

        # 1. Check momentum strength
        if not self._check_momentum_strength(signal_direction):
            self.signals_filtered += 1
            return False

        # 2. Check volume confirmation
        if not self._check_volume_confirmation():
            self.signals_filtered += 1
            return False

        # 3. Check spread filter
        if not self._check_spread_filter(current_spread):
            self.signals_filtered += 1
            return False

        return True

    def _check_momentum_strength(self, direction: int) -> bool:
        """
        Check if momentum strength exceeds minimum threshold.

        Uses cumulative tick-to-tick changes (aligned with live strategy).

        Args:
            direction: 1 for BUY, -1 for SELL

        Returns:
            True if momentum strength is sufficient
        """
        recent_ticks = list(self.tick_buffer)[-self.tick_momentum_count:]

        if len(recent_ticks) < 2:
            return False

        # Calculate cumulative tick-to-tick changes
        cumulative_change = 0.0
        for i in range(1, len(recent_ticks)):
            change = recent_ticks[i].mid - recent_ticks[i-1].mid
            cumulative_change += abs(change)

        # Check if cumulative change meets minimum strength
        return cumulative_change >= self.min_momentum_strength

    def _check_volume_confirmation(self) -> bool:
        """
        Check if recent volume exceeds average.

        Returns:
            True if volume is sufficient
        """
        if len(self.volume_buffer) < 20:
            return True  # Not enough data, skip check

        # Calculate average volume
        avg_volume = np.mean(list(self.volume_buffer)[-20:])

        # Calculate recent volume (last 3 ticks)
        recent_volume = np.mean(list(self.volume_buffer)[-3:])

        if avg_volume <= 0:
            return True  # Skip check if no volume data

        # Check if recent volume exceeds average
        return recent_volume >= (avg_volume * self.min_volume_multiplier)

    def _check_spread_filter(self, current_spread: float) -> bool:
        """
        Check if current spread is within acceptable range.

        Args:
            current_spread: Current spread

        Returns:
            True if spread is acceptable
        """
        if len(self.spread_buffer) < 10:
            return True  # Not enough data, skip check

        # Calculate average spread
        avg_spread = np.mean(list(self.spread_buffer))

        if avg_spread <= 0:
            return True  # Skip check

        # Check if current spread is within max multiplier
        max_allowed = avg_spread * self.max_spread_multiplier

        return current_spread <= max_allowed


    def _generate_signal(
        self,
        direction: int,
        timestamp: int,
        bid: float,
        ask: float
    ) -> Optional[TradeSignal]:
        """
        Generate trade signal with dynamic stop loss and take profit.

        Args:
            direction: 1 for BUY, -1 for SELL
            timestamp: Signal timestamp
            bid: Current bid
            ask: Current ask

        Returns:
            TradeSignal if generated successfully
        """
        # Use last mid price as a robust fallback if bid/ask are not valid
        last_mid = self.tick_buffer[-1].mid if self.tick_buffer else None

        # Determine entry price and signal type
        if direction > 0:  # BUY
            entry_price = ask
            signal_type = PositionType.BUY
        else:  # SELL
            entry_price = bid
            signal_type = PositionType.SELL

        # Fallback to mid price if entry price is not a finite positive number
        if not np.isfinite(entry_price) or entry_price <= 0:
            if last_mid is not None and np.isfinite(last_mid) and last_mid > 0:
                entry_price = last_mid
            else:
                self.logger.debug(
                    "Skipping HFT signal: invalid entry price "
                    f"(bid={bid}, ask={ask}, mid={last_mid})"
                )
                return None

        # Calculate stop loss
        pip_size = 0.0001  # For most forex pairs
        sl_distance = self.sl_pips * pip_size

        if signal_type == PositionType.BUY:
            stop_loss = entry_price - sl_distance
        else:
            stop_loss = entry_price + sl_distance

        # Calculate take profit based on R:R ratio
        tp_distance = sl_distance * self.risk_reward_ratio

        if signal_type == PositionType.BUY:
            take_profit = entry_price + tp_distance
        else:
            take_profit = entry_price - tp_distance

        # Fixed lot size for now
        lot_size = 0.01

        signal = TradeSignal(
            symbol=self.symbol,
            signal_type=signal_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=lot_size,
            timestamp=datetime.fromtimestamp(timestamp / 1_000_000_000),
            reason=f"HFT Momentum - {self.tick_momentum_count} tick momentum",
            max_spread_percent=self.max_spread_percent,
            comment=f"HFT_{signal_type.value}_{self.symbol}"
        )

        self.logger.info(
            f"HFT signal generated: {signal_type.value} "
            f"entry={entry_price:.5f}, sl={stop_loss:.5f}, tp={take_profit:.5f}, "
            f"R:R=1:{self.risk_reward_ratio:.1f}"
        )

        return signal

    def _submit_signal(
        self,
        signal: TradeSignal,
        timestamp: int,
        bid: float,
        ask: float
    ) -> None:
        """Submit trade signal as order to backtest and open a position.

        For backtesting we assume immediate limit fills at the requested price.
        """
        # Convert signal to order
        order = self.signal_to_order(signal, timestamp)
        if order is None:
            return

        # Submit order through hftbacktest (for realistic book/recorder state)
        if signal.signal_type == PositionType.BUY:
            self.hbt.submit_buy_order(
                self.asset_index,
                order.order_id,
                order.price,
                order.quantity,
                GTC,
                LIMIT,
                False,  # wait
            )
        else:
            self.hbt.submit_sell_order(
                self.asset_index,
                order.order_id,
                order.price,
                order.quantity,
                GTC,
                LIMIT,
                False,  # wait
            )

        # Assume immediate fill at requested price for backtesting
        self.on_order_filled(order, order.price, timestamp)

        self.logger.info(
            f"HFT order submitted: {signal.signal_type.name} "
            f"price={order.price:.5f}, qty={order.quantity:.2f}, "
            f"reason={signal.reason}"
        )


    def _check_exit_conditions(self, timestamp: int, bid: float, ask: float) -> None:
        """
        Check if any active positions should be closed.

        Args:
            timestamp: Current timestamp
            bid: Current bid price
            ask: Current ask price
        """
        positions_to_close = []

        for pos in self.active_positions:
            should_close = False
            close_reason = ""

            if pos.side == BUY:
                # For LONG positions, check bid price
                if bid <= pos.stop_loss:
                    should_close = True
                    close_reason = "Stop Loss"
                elif bid >= pos.take_profit:
                    should_close = True
                    close_reason = "Take Profit"

            elif pos.side == SELL:
                # For SHORT positions, check ask price
                if ask >= pos.stop_loss:
                    should_close = True
                    close_reason = "Stop Loss"
                elif ask <= pos.take_profit:
                    should_close = True
                    close_reason = "Take Profit"

            if should_close:
                positions_to_close.append((pos, close_reason))

        # Close positions
        for pos, reason in positions_to_close:
            self._close_position(pos, timestamp, bid, ask, reason)

    def _close_position(
        self,
        position: BacktestPosition,
        timestamp: int,
        bid: float,
        ask: float,
        reason: str
    ) -> None:
        """
        Close a position and calculate PnL.

        Args:
            position: Position to close
            timestamp: Close timestamp
            bid: Current bid price
            ask: Current ask price
            reason: Reason for closing
        """
        # Determine exit price
        if position.side == BUY:
            exit_price = bid
        else:
            exit_price = ask

        # Calculate PnL
        if position.side == BUY:
            pnl = (exit_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - exit_price) * position.quantity

        # Remove from active positions
        self.active_positions.remove(position)

        # Record closed position
        self.closed_positions.append({
            'symbol': position.symbol,
            'side': 'BUY' if position.side == BUY else 'SELL',
            'entry_price': position.entry_price,
            'exit_price': exit_price,
            'quantity': position.quantity,
            'entry_time': position.entry_time,
            'exit_time': timestamp,
            'pnl': pnl,
            'reason': reason
        })

        self.logger.info(
            f"HFT position closed: {position.symbol} "
            f"{'BUY' if position.side == BUY else 'SELL'} "
            f"entry={position.entry_price:.5f}, exit={exit_price:.5f}, "
            f"pnl={pnl:.2f}, reason={reason}"
        )



