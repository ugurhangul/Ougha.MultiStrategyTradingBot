"""
Fakeout Strategy Adapter for Backtesting.

This adapter bridges the FakeoutStrategy with the hftbacktest engine,
converting live trading logic to backtest-compatible format.

Key Adaptations:
- Converts tick data to strategy-compatible format
- Manages order submission through hftbacktest API
- Tracks positions and calculates PnL
- Handles stop loss and take profit execution
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


class FakeoutStrategyAdapter(BaseStrategyAdapter):
    """
    Adapter for FakeoutStrategy in backtesting environment.
    
    This adapter:
    - Processes tick data and generates fakeout signals
    - Submits orders through hftbacktest
    - Manages positions with stop loss and take profit
    - Tracks performance metrics
    
    Note: This is a simplified version for Phase 3.
    Full strategy logic will be integrated in later iterations.
    """
    
    def __init__(
        self,
        symbol: str,
        strategy_params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize Fakeout Strategy Adapter.
        
        Args:
            symbol: Trading symbol
            strategy_params: Strategy configuration parameters
        """
        super().__init__(
            symbol=symbol,
            strategy_name="FakeoutStrategy"
        )
        
        self.logger = get_logger()
        
        # Strategy parameters
        self.params = strategy_params or {}
        self.min_consolidation_bars = self.params.get('min_consolidation_bars', 10)
        self.breakout_threshold = self.params.get('breakout_threshold', 0.0005)
        self.max_spread_percent = self.params.get('max_spread_percent', 0.001)
        self.risk_reward_ratio = self.params.get('risk_reward_ratio', 2.0)
        
        # State tracking
        self.tick_count = 0
        self.last_price = None
        self.price_buffer = []
        self.max_buffer_size = 100
        
        # Range detection state
        self.range_high = None
        self.range_low = None
        self.consolidation_count = 0
        self.breakout_detected = False
        self.breakout_direction = None
        self.breakout_price = None
        
    def initialize(self, hbt, asset_index: int) -> None:
        """
        Initialize the adapter with backtest instance.
        
        Args:
            hbt: Backtest instance
            asset_index: Index of the asset in backtest
        """
        super().initialize(hbt, asset_index)
        
        self.logger.info(
            f"FakeoutStrategyAdapter initialized for {self.symbol} "
            f"(min_consolidation={self.min_consolidation_bars}, "
            f"breakout_threshold={self.breakout_threshold})"
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
        Process tick data and check for fakeout signals.
        
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
        
        # Update price buffer
        self.price_buffer.append(mid_price)
        if len(self.price_buffer) > self.max_buffer_size:
            self.price_buffer.pop(0)
        
        # Need minimum data
        if len(self.price_buffer) < self.min_consolidation_bars:
            return
        
        # Check for active positions
        if len(self.active_positions) > 0:
            # Monitor stop loss and take profit
            self._check_exit_conditions(timestamp, bid, ask)
            return
        
        # Check for pending orders
        if len(self.active_orders) > 0:
            return
        
        # Detect range and breakout
        self._detect_range_and_breakout(mid_price)
        
        # Check for fakeout signal
        signal = self._check_fakeout_signal(timestamp, mid_price, bid, ask)
        
        if signal:
            self._submit_signal(signal, timestamp, bid, ask)
    
    def _detect_range_and_breakout(self, current_price: float) -> None:
        """
        Detect consolidation range and breakout.
        
        Args:
            current_price: Current mid price
        """
        recent_prices = self.price_buffer[-self.min_consolidation_bars:]
        
        # Calculate range
        high = max(recent_prices)
        low = min(recent_prices)
        range_size = high - low
        
        # Check if in consolidation (range is small relative to price)
        if range_size / current_price < self.breakout_threshold:
            self.consolidation_count += 1
            self.range_high = high
            self.range_low = low
        else:
            # Check for breakout
            if self.consolidation_count >= self.min_consolidation_bars:
                if current_price > self.range_high:
                    self.breakout_detected = True
                    self.breakout_direction = 'UP'
                    self.breakout_price = current_price
                elif current_price < self.range_low:
                    self.breakout_detected = True
                    self.breakout_direction = 'DOWN'
                    self.breakout_price = current_price
            
            # Reset consolidation
            self.consolidation_count = 0

    def _check_fakeout_signal(
        self,
        timestamp: int,
        mid_price: float,
        bid: float,
        ask: float
    ) -> Optional[TradeSignal]:
        """
        Check for fakeout signal (price reversal back into range).

        Args:
            timestamp: Current timestamp
            mid_price: Current mid price
            bid: Current bid
            ask: Current ask

        Returns:
            TradeSignal if fakeout detected, None otherwise
        """
        if not self.breakout_detected:
            return None

        if self.range_high is None or self.range_low is None:
            return None

        # Check for fakeout (price reversal back into range)
        if self.breakout_direction == 'UP' and mid_price < self.range_high:
            # Fakeout detected - price broke up but reversed back down
            # Enter SHORT position
            entry_price = bid
            stop_loss = self.range_high + (self.range_high - self.range_low) * 0.1
            take_profit = entry_price - (stop_loss - entry_price) * self.risk_reward_ratio

            signal = TradeSignal(
                symbol=self.symbol,
                signal_type=PositionType.SELL,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                lot_size=0.01,  # Fixed lot size for now
                timestamp=datetime.fromtimestamp(timestamp / 1e9),
                reason="Fakeout_UP_Reversal",
                max_spread_percent=self.max_spread_percent,
                comment="FO_SHORT"
            )

            # Reset breakout state
            self.breakout_detected = False
            self.breakout_direction = None

            return signal

        elif self.breakout_direction == 'DOWN' and mid_price > self.range_low:
            # Fakeout detected - price broke down but reversed back up
            # Enter LONG position
            entry_price = ask
            stop_loss = self.range_low - (self.range_high - self.range_low) * 0.1
            take_profit = entry_price + (entry_price - stop_loss) * self.risk_reward_ratio

            signal = TradeSignal(
                symbol=self.symbol,
                signal_type=PositionType.BUY,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                lot_size=0.01,  # Fixed lot size for now
                timestamp=datetime.fromtimestamp(timestamp / 1e9),
                reason="Fakeout_DOWN_Reversal",
                max_spread_percent=self.max_spread_percent,
                comment="FO_LONG"
            )

            # Reset breakout state
            self.breakout_detected = False
            self.breakout_direction = None

            return signal

        return None

    def _submit_signal(
        self,
        signal: TradeSignal,
        timestamp: int,
        bid: float,
        ask: float
    ) -> None:
        """
        Submit trade signal as order to backtest.

        Args:
            signal: Trade signal to submit
            timestamp: Current timestamp
            bid: Current bid
            ask: Current ask
        """
        # Convert signal to order
        order = self.signal_to_order(signal, timestamp)

        # Submit order through hftbacktest
        if signal.signal_type == PositionType.BUY:
            self.hbt.submit_buy_order(
                self.asset_index,
                order.order_id,
                order.price,
                order.quantity,
                GTC,
                LIMIT,
                False  # wait
            )
        else:  # SELL
            self.hbt.submit_sell_order(
                self.asset_index,
                order.order_id,
                order.price,
                order.quantity,
                GTC,
                LIMIT,
                False  # wait
            )

        self.logger.info(
            f"Submitted {signal.signal_type.name} order: "
            f"price={order.price:.5f}, qty={order.quantity:.2f}, "
            f"reason={signal.reason}"
        )

    def _check_exit_conditions(
        self,
        timestamp: int,
        bid: float,
        ask: float
    ) -> None:
        """
        Check if any active positions should be closed (SL/TP hit).

        Args:
            timestamp: Current timestamp
            bid: Current bid
            ask: Current ask
        """
        for position in self.active_positions[:]:  # Copy list to allow modification
            # Check stop loss and take profit
            if position.side == BUY:
                # For long positions, check bid price
                if bid <= position.stop_loss:
                    self._close_position(position, bid, timestamp, "StopLoss")
                elif bid >= position.take_profit:
                    self._close_position(position, bid, timestamp, "TakeProfit")
            else:  # SELL
                # For short positions, check ask price
                if ask >= position.stop_loss:
                    self._close_position(position, ask, timestamp, "StopLoss")
                elif ask <= position.take_profit:
                    self._close_position(position, ask, timestamp, "TakeProfit")

    def _close_position(
        self,
        position: BacktestPosition,
        exit_price: float,
        timestamp: int,
        reason: str
    ) -> None:
        """
        Close a position.

        Args:
            position: Position to close
            exit_price: Exit price
            timestamp: Exit timestamp
            reason: Reason for closure
        """
        # Calculate PnL
        if position.side == BUY:
            pnl = (exit_price - position.entry_price) * position.quantity
        else:  # SELL
            pnl = (position.entry_price - exit_price) * position.quantity

        # Update position
        position.exit_price = exit_price
        position.exit_time = timestamp
        position.pnl = pnl

        # Move to closed positions
        self.active_positions.remove(position)
        self.closed_positions.append(position)

        self.logger.info(
            f"Closed position: {position.side} {position.quantity:.2f} @ {exit_price:.5f}, "
            f"PnL={pnl:.2f}, reason={reason}"
        )

