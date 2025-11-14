"""
Base Strategy Adapter for Backtesting.

This module provides the base adapter class that bridges live trading strategies
with the hftbacktest backtesting engine.

The adapter pattern allows existing strategies to work in backtesting mode
without modifying their core logic.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

import numpy as np
from numba import njit

from src.models.models import TradeSignal, PositionType


@dataclass
class BacktestOrder:
    """Represents an order in the backtest."""
    order_id: int
    symbol: str
    side: int  # BUY or SELL constant from hftbacktest
    price: float
    quantity: float
    timestamp: int  # microseconds
    signal: TradeSignal  # Original signal that generated this order


@dataclass
class BacktestPosition:
    """Represents a position in the backtest."""
    symbol: str
    side: int
    entry_price: float
    quantity: float
    entry_time: int  # microseconds
    stop_loss: float
    take_profit: float
    signal: TradeSignal


class BaseStrategyAdapter(ABC):
    """
    Base adapter for converting live strategies to backtest-compatible format.

    This adapter:
    - Translates live strategy signals to backtest orders
    - Manages position state in backtest mode
    - Handles order execution callbacks
    - Provides market data in the format expected by strategies

    Design Pattern: Adapter Pattern
    - Adapts BaseStrategy interface to hftbacktest execution model
    - Allows strategies to work in both live and backtest modes
    """

    def __init__(self, symbol: str, strategy_name: str):
        """Initialize strategy adapter.

        Args:
            symbol: Trading symbol
            strategy_name: Name of the strategy being adapted
        """
        self.symbol = symbol
        self.strategy_name = strategy_name

        # Backtest runtime context (set during initialize)
        self.hbt = None
        self.asset_index: int = 0

        # Order/position tracking
        self.active_orders: Dict[int, BacktestOrder] = {}
        self.active_positions: List[BacktestPosition] = []
        self.closed_positions: List[BacktestPosition] = []
        self.order_id_counter = 0

    def generate_order_id(self) -> int:
        """Generate unique order ID."""
        self.order_id_counter += 1
        return self.order_id_counter

    @abstractmethod
    def on_tick(self, timestamp: int, bid: float, ask: float,
                bid_qty: float, ask_qty: float) -> Optional[TradeSignal]:
        """
        Process tick data and generate trading signal.

        This method should call the underlying strategy's on_tick() method
        and return any generated signals.

        Args:
            timestamp: Current timestamp in microseconds
            bid: Current bid price
            ask: Current ask price
            bid_qty: Bid quantity
            ask_qty: Ask quantity

        Returns:
            TradeSignal if signal generated, None otherwise
        """
        pass

    @abstractmethod
    def initialize(self, hbt, asset_index: int) -> None:
        """Initialize the strategy adapter with backtest context.

        Args:
            hbt: Backtest instance (ROIVectorMarketDepthBacktest or HashMapMarketDepthBacktest)
            asset_index: Index of the asset in the backtest
        """
        # Store backtest context so subclasses can access it
        self.hbt = hbt
        self.asset_index = asset_index

    def signal_to_order(self, signal: TradeSignal, timestamp: int) -> Optional[BacktestOrder]:
        """
        Convert TradeSignal to BacktestOrder.

        Args:
            signal: Trade signal from strategy
            timestamp: Current timestamp in microseconds

        Returns:
            BacktestOrder or None if conversion fails
        """
        if signal is None:
            return None

        # Import hftbacktest constants
        from hftbacktest import BUY, SELL

        # Convert PositionType to hftbacktest side
        side = BUY if signal.signal_type == PositionType.BUY else SELL

        order = BacktestOrder(
            order_id=self.generate_order_id(),
            symbol=signal.symbol,
            side=side,
            price=signal.entry_price,
            quantity=signal.lot_size,
            timestamp=timestamp,
            signal=signal
        )

        self.active_orders[order.order_id] = order
        return order

    def on_order_filled(self, order: BacktestOrder, fill_price: float,
                       fill_time: int) -> None:
        """
        Handle order fill event.

        Args:
            order: The filled order
            fill_price: Actual fill price
            fill_time: Fill timestamp in microseconds
        """
        # Remove from active orders
        if order.order_id in self.active_orders:
            del self.active_orders[order.order_id]

        # Create position
        position = BacktestPosition(
            symbol=order.symbol,
            side=order.side,
            entry_price=fill_price,
            quantity=order.quantity,
            entry_time=fill_time,
            stop_loss=order.signal.stop_loss,
            take_profit=order.signal.take_profit,
            signal=order.signal
        )

        self.active_positions.append(position)

    def on_position_closed(self, position: BacktestPosition, close_price: float,
                          close_time: int, reason: str) -> None:
        """
        Handle position close event.

        Args:
            position: The closed position
            close_price: Close price
            close_time: Close timestamp in microseconds
            reason: Reason for closure (TP, SL, manual, etc.)
        """
        # Remove from active positions
        if position in self.active_positions:
            self.active_positions.remove(position)

        # Add to closed positions
        self.closed_positions.append(position)

    def get_active_position_count(self) -> int:
        """Get number of active positions."""
        return len(self.active_positions)

    def has_active_position(self) -> bool:
        """Check if there are any active positions."""
        return len(self.active_positions) > 0

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get adapter statistics.

        Returns:
            Dictionary with statistics
        """
        total_trades = len(self.closed_positions)
        winning_trades = sum(1 for p in self.closed_positions
                           if self._is_winning_position(p))

        return {
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'win_rate': winning_trades / total_trades if total_trades > 0 else 0.0,
            'active_positions': len(self.active_positions),
            'active_orders': len(self.active_orders)
        }

    def _is_winning_position(self, position: BacktestPosition) -> bool:
        """
        Determine if a position was profitable.

        Note: This is a simplified check. Actual P&L calculation
        should be done by the backtest engine.

        Args:
            position: Position to check

        Returns:
            True if position was likely profitable
        """
        # This is a placeholder - actual P&L should come from backtest engine
        return True
