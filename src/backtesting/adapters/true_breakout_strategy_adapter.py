"""
True Breakout Strategy Adapter for Backtesting.

This adapter bridges the TrueBreakoutStrategy with the hftbacktest engine,
converting live trading logic to backtest-compatible format.

Key Adaptations:
- Detects valid breakouts (open inside, close outside range)
- Waits for retest of breakout level
- Confirms continuation with volume
- Manages positions with stop loss and take profit

Strategy Logic:
1. Detect consolidation range
2. Identify valid breakout (open inside, close outside)
3. Wait for retest (pullback to breakout level)
4. Confirm continuation in breakout direction
5. Enter trade with SL below/above pattern
"""

from typing import Optional, Dict, Any
from datetime import datetime
import numpy as np

from hftbacktest import BUY, SELL, LIMIT, GTC

from src.backtesting.adapters.base_strategy_adapter import (
    BaseStrategyAdapter,
    BacktestOrder,
    BacktestPosition
)
from src.models.data_models import TradeSignal, PositionType
from src.utils.logger import get_logger


class TrueBreakoutStrategyAdapter(BaseStrategyAdapter):
    """
    Adapter for TrueBreakoutStrategy in backtesting environment.

    This adapter:
    - Detects valid breakouts with volume confirmation
    - Waits for retest of breakout level
    - Confirms continuation before entry
    - Manages positions with pattern-based stop loss
    """

    def __init__(
        self,
        symbol: str,
        strategy_params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize True Breakout Strategy Adapter.

        Args:
            symbol: Trading symbol
            strategy_params: Strategy configuration parameters
        """
        super().__init__(
            symbol=symbol,
            strategy_name="TrueBreakoutStrategy"
        )

        self.logger = get_logger()

        # Strategy parameters
        self.params = strategy_params or {}
        self.min_consolidation_bars = self.params.get('min_consolidation_bars', 15)
        self.breakout_threshold = self.params.get('breakout_threshold', 0.0008)
        self.min_breakout_volume_multiplier = self.params.get('min_breakout_volume_multiplier', 1.5)
        self.retest_tolerance_percent = self.params.get('retest_tolerance_percent', 0.0005)
        self.max_spread_percent = self.params.get('max_spread_percent', 0.001)
        self.risk_reward_ratio = self.params.get('risk_reward_ratio', 2.0)
        self.sl_buffer_pips = self.params.get('sl_buffer_pips', 5)

        # State tracking
        self.tick_count = 0
        self.price_buffer = []
        self.volume_buffer = []
        self.max_buffer_size = 100

        # Range detection state
        self.range_high = None
        self.range_low = None
        self.consolidation_count = 0
        self.avg_volume = None

        # Breakout state
        self.breakout_detected = False
        self.breakout_direction = None  # 'UP' or 'DOWN'
        self.breakout_price = None
        self.breakout_volume = None
        self.breakout_volume_ok = False

        # Retest state
        self.retest_detected = False

        # Continuation state
        self.continuation_detected = False

    def initialize(self, hbt, asset_index: int) -> None:
        """
        Initialize the adapter with backtest instance.

        Args:
            hbt: Backtest instance
            asset_index: Index of the asset in backtest
        """
        super().initialize(hbt, asset_index)

        self.logger.info(
            f"TrueBreakoutStrategyAdapter initialized for {self.symbol} "
            f"(min_consolidation={self.min_consolidation_bars}, "
            f"breakout_threshold={self.breakout_threshold}, "
            f"volume_mult={self.min_breakout_volume_multiplier})"
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
        Process tick data and check for true breakout signals.

        Args:
            timestamp: Tick timestamp in nanoseconds
            bid: Best bid price
            ask: Best ask price
            bid_qty: Bid quantity
            ask_qty: Ask quantity
        """
        self.tick_count += 1

        # Calculate mid price
        mid_price = (bid + ask) / 2.0
        spread = ask - bid
        spread_percent = spread / mid_price if mid_price > 0 else 0

        # Check spread filter
        if spread_percent > self.max_spread_percent:
            return

        # Update buffers
        volume = (bid_qty + ask_qty) / 2.0  # Approximate volume
        self.price_buffer.append(mid_price)
        self.volume_buffer.append(volume)

        if len(self.price_buffer) > self.max_buffer_size:
            self.price_buffer.pop(0)
            self.volume_buffer.pop(0)

        # Need minimum data
        if len(self.price_buffer) < self.min_consolidation_bars:
            return

        # Calculate average volume
        if len(self.volume_buffer) >= 10:
            self.avg_volume = np.mean(self.volume_buffer[-20:]) if len(self.volume_buffer) >= 20 else np.mean(self.volume_buffer)

        # Check for active positions
        if len(self.active_positions) > 0:
            self._check_exit_conditions(timestamp, bid, ask)
            return

        # Check for pending orders
        if len(self.active_orders) > 0:
            return

        # State machine for true breakout detection
        if not self.breakout_detected:
            # Stage 1: Detect range and breakout
            self._detect_range_and_breakout(mid_price, volume)
        elif not self.retest_detected:
            # Stage 2: Wait for retest
            self._detect_retest(mid_price)
        elif not self.continuation_detected:
            # Stage 3: Check for continuation
            signal = self._check_continuation(timestamp, mid_price, bid, ask)
            if signal:
                self._submit_signal(signal, timestamp, bid, ask)
                # Reset state after signal
                self._reset_state()

    def _detect_range_and_breakout(self, current_price: float, current_volume: float) -> None:
        """
        Detect consolidation range and valid breakout.

        Valid breakout requires:
        - Open inside range
        - Close outside range
        - High volume (> avg_volume * multiplier)

        Args:
            current_price: Current mid price
            current_volume: Current volume
        """
        recent_prices = self.price_buffer[-self.min_consolidation_bars:]

        # Calculate range
        high = max(recent_prices)
        low = min(recent_prices)
        range_size = high - low

        # Check if in consolidation
        if range_size / current_price < self.breakout_threshold:
            self.consolidation_count += 1
            self.range_high = high
            self.range_low = low
        else:
            # Check for valid breakout
            if self.consolidation_count >= self.min_consolidation_bars:
                # Get previous price (simulating candle open)
                prev_price = self.price_buffer[-2] if len(self.price_buffer) >= 2 else current_price

                # Check for valid breakout ABOVE
                if prev_price >= self.range_low and prev_price <= self.range_high:
                    # Open inside range
                    if current_price > self.range_high:
                        # Close above range - valid upward breakout
                        # Check volume
                        volume_ok = self._check_breakout_volume(current_volume)

                        self.breakout_detected = True
                        self.breakout_direction = 'UP'
                        self.breakout_price = current_price
                        self.breakout_volume = current_volume
                        self.breakout_volume_ok = volume_ok

                        vol_status = "✓" if volume_ok else "✗"
                        self.logger.info(
                            f"Breakout ABOVE detected: price={current_price:.5f}, "
                            f"range=[{self.range_low:.5f}, {self.range_high:.5f}], "
                            f"volume_ok={vol_status}"
                        )
                        return

                    elif current_price < self.range_low:
                        # Close below range - valid downward breakout
                        # Check volume
                        volume_ok = self._check_breakout_volume(current_volume)

                        self.breakout_detected = True
                        self.breakout_direction = 'DOWN'
                        self.breakout_price = current_price
                        self.breakout_volume = current_volume
                        self.breakout_volume_ok = volume_ok

                        vol_status = "✓" if volume_ok else "✗"
                        self.logger.info(
                            f"Breakout BELOW detected: price={current_price:.5f}, "
                            f"range=[{self.range_low:.5f}, {self.range_high:.5f}], "
                            f"volume_ok={vol_status}"
                        )
                        return

            # Reset consolidation
            self.consolidation_count = 0

    def _check_breakout_volume(self, volume: float) -> bool:
        """
        Check if breakout volume is high enough.

        Args:
            volume: Breakout volume

        Returns:
            True if volume is high enough
        """
        if self.avg_volume is None or self.avg_volume == 0:
            return True  # Can't check, assume OK

        return volume >= (self.avg_volume * self.min_breakout_volume_multiplier)

    def _detect_retest(self, current_price: float) -> None:
        """
        Detect retest of breakout level.

        Retest criteria:
        - Price pulls back to breakout level (within tolerance)
        - Price bounces off the level (doesn't break back through)

        Args:
            current_price: Current mid price
        """
        if not self.breakout_detected:
            return

        if self.breakout_direction == 'UP':
            # For upward breakout, wait for pullback to range_high
            retest_level = self.range_high
            retest_range = retest_level * self.retest_tolerance_percent

            # Check if price touched or came close to the level
            touched_level = current_price <= (retest_level + retest_range)
            bounced_off = current_price >= retest_level

            if touched_level and bounced_off:
                self.retest_detected = True
                self.logger.info(
                    f"Retest detected (UP): price={current_price:.5f}, "
                    f"level={retest_level:.5f}"
                )

        elif self.breakout_direction == 'DOWN':
            # For downward breakout, wait for pullback to range_low
            retest_level = self.range_low
            retest_range = retest_level * self.retest_tolerance_percent

            # Check if price touched or came close to the level
            touched_level = current_price >= (retest_level - retest_range)
            bounced_off = current_price <= retest_level

            if touched_level and bounced_off:
                self.retest_detected = True
                self.logger.info(
                    f"Retest detected (DOWN): price={current_price:.5f}, "
                    f"level={retest_level:.5f}"
                )


    def _check_continuation(
        self,
        timestamp: int,
        current_price: float,
        bid: float,
        ask: float
    ) -> Optional[TradeSignal]:
        """
        Check for continuation after retest.

        Continuation criteria:
        - Price moves back in breakout direction
        - For UP: price > range_high
        - For DOWN: price < range_low

        Args:
            timestamp: Current timestamp
            current_price: Current mid price
            bid: Current bid
            ask: Current ask

        Returns:
            TradeSignal if continuation detected, None otherwise
        """
        if not self.retest_detected:
            return None

        if self.breakout_direction == 'UP':
            # Check for continuation above range_high
            if current_price > self.range_high:
                self.continuation_detected = True
                self.logger.info(
                    f"Continuation detected (UP): price={current_price:.5f}, "
                    f"level={self.range_high:.5f}"
                )

                # Generate BUY signal
                return self._generate_buy_signal(timestamp, current_price, bid, ask)

        elif self.breakout_direction == 'DOWN':
            # Check for continuation below range_low
            if current_price < self.range_low:
                self.continuation_detected = True
                self.logger.info(
                    f"Continuation detected (DOWN): price={current_price:.5f}, "
                    f"level={self.range_low:.5f}"
                )

                # Generate SELL signal
                return self._generate_sell_signal(timestamp, current_price, bid, ask)

        return None

    def _generate_buy_signal(
        self,
        timestamp: int,
        mid_price: float,
        bid: float,
        ask: float
    ) -> TradeSignal:
        """
        Generate BUY signal for true breakout.

        Args:
            timestamp: Signal timestamp
            mid_price: Current mid price
            bid: Current bid
            ask: Current ask

        Returns:
            TradeSignal for BUY
        """
        # Entry at ask price
        entry_price = ask

        # Stop loss below range_low with buffer
        # Convert buffer pips to price (assuming 5-digit pricing)
        pip_size = 0.0001  # For most forex pairs
        buffer = self.sl_buffer_pips * pip_size
        stop_loss = self.range_low - buffer

        # Take profit based on risk-reward ratio
        sl_distance = abs(entry_price - stop_loss)
        take_profit = entry_price + (sl_distance * self.risk_reward_ratio)

        # Fixed lot size for now
        lot_size = 0.01

        signal = TradeSignal(
            symbol=self.symbol,
            signal_type=PositionType.BUY,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=lot_size,
            timestamp=datetime.fromtimestamp(timestamp / 1_000_000_000),
            reason=f"True Breakout BUY - Range [{self.range_low:.5f}, {self.range_high:.5f}]",
            max_spread_percent=self.max_spread_percent,
            comment=f"TB_BUY_{self.symbol}"
        )

        self.logger.info(
            f"BUY signal generated: entry={entry_price:.5f}, "
            f"sl={stop_loss:.5f}, tp={take_profit:.5f}"
        )

        return signal

    def _generate_sell_signal(
        self,
        timestamp: int,
        mid_price: float,
        bid: float,
        ask: float
    ) -> TradeSignal:
        """
        Generate SELL signal for true breakout.

        Args:
            timestamp: Signal timestamp
            mid_price: Current mid price
            bid: Current bid
            ask: Current ask

        Returns:
            TradeSignal for SELL
        """
        # Entry at bid price
        entry_price = bid

        # Stop loss above range_high with buffer
        # Convert buffer pips to price (assuming 5-digit pricing)
        pip_size = 0.0001  # For most forex pairs
        buffer = self.sl_buffer_pips * pip_size
        stop_loss = self.range_high + buffer

        # Take profit based on risk-reward ratio
        sl_distance = abs(entry_price - stop_loss)
        take_profit = entry_price - (sl_distance * self.risk_reward_ratio)

        # Fixed lot size for now
        lot_size = 0.01

        signal = TradeSignal(
            symbol=self.symbol,
            signal_type=PositionType.SELL,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=lot_size,
            timestamp=datetime.fromtimestamp(timestamp / 1_000_000_000),
            reason=f"True Breakout SELL - Range [{self.range_low:.5f}, {self.range_high:.5f}]",
            max_spread_percent=self.max_spread_percent,
            comment=f"TB_SELL_{self.symbol}"
        )

        self.logger.info(
            f"SELL signal generated: entry={entry_price:.5f}, "
            f"sl={stop_loss:.5f}, tp={take_profit:.5f}"
        )

        return signal

    def _reset_state(self) -> None:
        """Reset strategy state after signal generation."""
        self.breakout_detected = False
        self.breakout_direction = None
        self.breakout_price = None
        self.breakout_volume = None
        self.breakout_volume_ok = False
        self.retest_detected = False
        self.continuation_detected = False
        self.range_high = None
        self.range_low = None
        self.consolidation_count = 0

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
            f"Position closed: {position.symbol} "
            f"{'BUY' if position.side == BUY else 'SELL'} "
            f"entry={position.entry_price:.5f}, exit={exit_price:.5f}, "
            f"pnl={pnl:.2f}, reason={reason}"
        )


