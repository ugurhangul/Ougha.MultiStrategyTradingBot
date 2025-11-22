"""
Martingale Position Sizer

Position sizing strategy that increases lot size after losses to recover previous losses.
WARNING: High risk strategy - can lead to large drawdowns if not properly managed.
"""

from typing import Dict, Any, Optional
from enum import Enum

from src.risk.position_sizing.base_position_sizer import BasePositionSizer
from src.risk.position_sizing.position_sizer_factory import register_position_sizer
from src.core.mt5_connector import MT5Connector
from src.utils.logger import get_logger


class MartingaleType(Enum):
    """Martingale progression types"""
    CLASSIC_MULTIPLIER = "classic_multiplier"  # new_lot = prev_lot × multiplier
    MULTIPLIER_WITH_SUM = "multiplier_with_sum"  # new_lot = (prev_lot × multiplier) + initial
    SUM_WITH_INITIAL = "sum_with_initial"  # new_lot = prev_lot + initial


@register_position_sizer(
    "martingale",
    description="Martingale progression - increases lot size after losses (HIGH RISK)",
    default=False
)
class MartingalePositionSizer(BasePositionSizer):
    """
    Martingale position sizing strategy.

    Increases lot size after losses to recover previous losses and make a profit.
    Resets to initial lot size after a win.

    WARNING: This is a high-risk strategy that can lead to large drawdowns.
    Use with caution and proper risk management.

    Features:
    - Multiple progression types (classic, multiplier+sum, sum)
    - Configurable multiplier
    - Maximum orders per round (cycle reset)
    - Consecutive loss protection
    - Symbol-aware lot normalization
    """

    def __init__(self, symbol: str, connector: MT5Connector,
                 martingale_type: MartingaleType = MartingaleType.CLASSIC_MULTIPLIER,
                 multiplier: float = 1.5,
                 max_orders_per_round: int = 3,
                 max_consecutive_losses: int = 5,
                 enable_loss_protection: bool = True,
                 max_lot_size: float = 5.0,
                 **kwargs):
        """
        Initialize martingale position sizer.

        Args:
            symbol: Trading symbol
            connector: MT5 connector for symbol info
            martingale_type: Type of martingale progression
            multiplier: Multiplier for lot size progression
            max_orders_per_round: Maximum orders before cycle reset
            max_consecutive_losses: Maximum consecutive losses before disabling
            enable_loss_protection: Enable consecutive loss protection
            max_lot_size: Maximum allowed lot size
            **kwargs: Additional parameters
        """
        super().__init__(symbol, **kwargs)
        self.logger = get_logger()
        self.connector = connector

        # Configuration
        self.martingale_type = martingale_type
        self.multiplier = multiplier
        self.max_orders_per_round = max_orders_per_round
        self.max_consecutive_losses = max_consecutive_losses
        self.enable_loss_protection = enable_loss_protection
        self.max_lot_size = max_lot_size

        # State
        self.initial_lot_size: float = 0.0
        self.current_lot_size: float = 0.0
        self.order_count_in_round: int = 0
        self.consecutive_losses: int = 0
        self.loss_limit_reached: bool = False

        # Statistics
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
        self.total_profit: float = 0.0
        self.max_lot_reached: float = 0.0

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
            f"Martingale position sizer initialized for {self.symbol}: "
            f"{initial_lot_size:.2f} lots (Type: {self.martingale_type.value}, "
            f"Multiplier: {self.multiplier}x, Max rounds: {self.max_orders_per_round})",
            self.symbol
        )

        return True

    def calculate_lot_size(self) -> float:
        """
        Calculate lot size for next trade.

        Returns:
            Lot size (may be increased due to martingale progression)
        """
        if not self.is_enabled():
            self.logger.warning(
                f"Martingale position sizer disabled for {self.symbol} - returning 0",
                self.symbol
            )
            return 0.0

        return self.current_lot_size

    def on_trade_closed(self, profit: float, lot_size: float) -> None:
        """
        Update martingale state after trade closure.

        Args:
            profit: Trade profit/loss
            lot_size: Lot size of closed trade
        """
        self.total_trades += 1
        self.total_profit += profit

        if profit < 0:
            # LOSS - Increase lot size
            self._handle_loss(profit, lot_size)
        else:
            # PROFIT - Reset martingale
            self._handle_profit(profit)

    def _handle_loss(self, profit: float, lot_size: float) -> None:
        """Handle loss and update martingale progression."""
        self.losing_trades += 1
        self.order_count_in_round += 1
        self.consecutive_losses += 1

        self.logger.warning(
            f"Trade LOSS: ${profit:.2f} | Consecutive losses: {self.consecutive_losses}",
            self.symbol
        )

        # Check consecutive loss limit
        if (self.enable_loss_protection and
            self.consecutive_losses >= self.max_consecutive_losses):
            self.loss_limit_reached = True
            self.logger.error(
                f"*** CONSECUTIVE LOSS LIMIT REACHED ({self.max_consecutive_losses}) ***",
                self.symbol
            )
            self.logger.error(
                f"Martingale position sizer DISABLED for {self.symbol}",
                self.symbol
            )
            return

        # Check if martingale cycle should reset
        if self.order_count_in_round >= self.max_orders_per_round:
            self.logger.warning(
                f"Max orders per round ({self.max_orders_per_round}) reached - resetting martingale",
                self.symbol
            )
            self.order_count_in_round = 0
            self.current_lot_size = self.initial_lot_size
        else:
            # Apply martingale progression
            self.current_lot_size = self._calculate_next_lot_size(lot_size)

            # Track maximum lot size reached
            if self.current_lot_size > self.max_lot_reached:
                self.max_lot_reached = self.current_lot_size

            self.logger.info(
                f"Martingale progression: {lot_size:.2f} -> {self.current_lot_size:.2f} "
                f"(Round: {self.order_count_in_round}/{self.max_orders_per_round})",
                self.symbol
            )

    def _handle_profit(self, profit: float) -> None:
        """Handle profit and reset martingale."""
        self.winning_trades += 1
        self.order_count_in_round = 0
        self.current_lot_size = self.initial_lot_size
        self.consecutive_losses = 0

        self.logger.info(
            f"Trade PROFIT: ${profit:.2f} | Martingale reset to initial lot: {self.initial_lot_size:.2f}",
            self.symbol
        )

    def _calculate_next_lot_size(self, previous_lot: float) -> float:
        """
        Calculate next lot size based on martingale type.

        Args:
            previous_lot: Previous lot size

        Returns:
            Next lot size
        """
        if self.martingale_type == MartingaleType.CLASSIC_MULTIPLIER:
            # new_lot = prev_lot * multiplier
            next_lot = previous_lot * self.multiplier

        elif self.martingale_type == MartingaleType.MULTIPLIER_WITH_SUM:
            # new_lot = (prev_lot * multiplier) + initial_lot
            next_lot = (previous_lot * self.multiplier) + self.initial_lot_size

        elif self.martingale_type == MartingaleType.SUM_WITH_INITIAL:
            # new_lot = prev_lot + initial_lot
            next_lot = previous_lot + self.initial_lot_size

        else:
            next_lot = previous_lot

        # Apply maximum lot size limit
        next_lot = min(next_lot, self.max_lot_size)

        # Normalize to symbol lot step
        next_lot = self._normalize_lot_size(next_lot)

        return next_lot

    def _normalize_lot_size(self, lot_size: float) -> float:
        """
        Normalize lot size to symbol's lot step and limits.

        Args:
            lot_size: Raw lot size

        Returns:
            Normalized lot size
        """
        symbol_info = self.connector.get_symbol_info(self.symbol)
        if symbol_info is None:
            self.logger.warning(f"Could not get symbol info for {self.symbol}, using raw lot size")
            return lot_size

        lot_step = symbol_info['lot_step']
        min_lot = symbol_info['min_lot']
        max_lot = symbol_info['max_lot']

        # Round to lot step using Decimal for precise rounding
        from decimal import Decimal, ROUND_HALF_UP

        lot_size_decimal = Decimal(str(lot_size))
        lot_step_decimal = Decimal(str(lot_step))
        steps = (lot_size_decimal / lot_step_decimal).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        normalized = float(steps * lot_step_decimal)

        # Ensure within symbol limits
        normalized = max(min_lot, min(max_lot, normalized))

        return normalized

    def reset(self) -> None:
        """
        Reset martingale to initial state.
        """
        self.current_lot_size = self.initial_lot_size
        self.order_count_in_round = 0
        self.consecutive_losses = 0
        self.loss_limit_reached = False
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.max_lot_reached = 0.0

        self.logger.info(f"Martingale position sizer reset for {self.symbol}", self.symbol)

    def get_state(self) -> Dict[str, Any]:
        """
        Get current state.

        Returns:
            State dictionary
        """
        return {
            'type': 'martingale',
            'symbol': self.symbol,
            'is_initialized': self.is_initialized,
            'is_enabled': self.is_enabled(),
            'initial_lot_size': self.initial_lot_size,
            'current_lot_size': self.current_lot_size,
            'order_count_in_round': self.order_count_in_round,
            'max_orders_per_round': self.max_orders_per_round,
            'consecutive_losses': self.consecutive_losses,
            'max_consecutive_losses': self.max_consecutive_losses,
            'loss_limit_reached': self.loss_limit_reached,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0,
            'total_profit': self.total_profit,
            'max_lot_reached': self.max_lot_reached,
            'config': {
                'martingale_type': self.martingale_type.value,
                'multiplier': self.multiplier,
                'max_lot_size': self.max_lot_size,
                'enable_loss_protection': self.enable_loss_protection
            }
        }

    def is_enabled(self) -> bool:
        """
        Check if martingale is enabled.

        Returns:
            False if loss limit reached, True otherwise
        """
        return self.is_initialized and not self.loss_limit_reached

