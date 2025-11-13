"""
Order execution and management facade.

This module provides a unified interface for order execution and position management,
delegating to specialized components.
"""

from typing import Optional, TYPE_CHECKING

from src.models.data_models import TradeSignal
from src.core.mt5_connector import MT5Connector
from src.execution.position_persistence import PositionPersistence
from src.utils.logger import get_logger
from src.utils.autotrading_cooldown import AutoTradingCooldown
from src.utils.price_normalization_service import PriceNormalizationService
from src.execution.order_management.order_executor import OrderExecutor
from src.execution.order_management.position_modifier import PositionModifier

if TYPE_CHECKING:
    from src.risk.risk_manager import RiskManager


class OrderManager:
    """
    Manages order execution and modification.

    This is a facade class that delegates to specialized components:
    - OrderExecutor: Handles order execution
    - PositionModifier: Handles position modification and closing
    """

    def __init__(self, connector: MT5Connector, magic_number: int, trade_comment: str,
                 persistence: Optional[PositionPersistence] = None,
                 cooldown_manager: Optional[AutoTradingCooldown] = None,
                 risk_manager: Optional['RiskManager'] = None):
        """
        Initialize order manager.

        Args:
            connector: MT5 connector instance
            magic_number: Magic number for orders
            trade_comment: Comment for trades
            persistence: Position persistence instance (optional)
            cooldown_manager: AutoTrading cooldown manager (optional)
            risk_manager: Risk manager instance (optional, for position limit checks)
        """
        self.connector = connector
        self.magic_number = magic_number
        self.trade_comment = trade_comment
        self.logger = get_logger()

        # Position persistence
        self.persistence = persistence if persistence is not None else PositionPersistence()

        # AutoTrading cooldown manager
        self.cooldown = cooldown_manager if cooldown_manager is not None else AutoTradingCooldown()

        # Price normalization service
        self.price_normalizer = PriceNormalizationService(connector)

        # Initialize specialized components
        self.order_executor = OrderExecutor(
            connector=connector,
            magic_number=magic_number,
            persistence=self.persistence,
            cooldown=self.cooldown,
            price_normalizer=self.price_normalizer,
            logger=self.logger,
            risk_manager=risk_manager
        )

        self.position_modifier = PositionModifier(
            connector=connector,
            magic_number=magic_number,
            trade_comment=trade_comment,
            persistence=self.persistence,
            cooldown=self.cooldown,
            price_normalizer=self.price_normalizer,
            logger=self.logger
        )

    def normalize_price(self, symbol: str, price: float) -> float:
        """
        Normalize price to symbol's digits.

        Delegates to PriceNormalizationService.

        Args:
            symbol: Symbol name
            price: Price to normalize

        Returns:
            Normalized price
        """
        return self.price_normalizer.normalize_price(symbol, price)

    def normalize_volume(self, symbol: str, volume: float) -> float:
        """
        Normalize volume to symbol's lot step.

        Delegates to PriceNormalizationService.

        Args:
            symbol: Symbol name
            volume: Volume to normalize

        Returns:
            Normalized volume
        """
        return self.price_normalizer.normalize_volume(symbol, volume)

    def execute_signal(self, signal: TradeSignal) -> Optional[int]:
        """
        Execute a trade signal.

        Delegates to OrderExecutor.

        Args:
            signal: TradeSignal object

        Returns:
            Ticket number if successful, None otherwise
        """
        return self.order_executor.execute_signal(signal)

    def modify_position(self, ticket: int, sl: Optional[float] = None,
                       tp: Optional[float] = None):
        """
        Modify position SL/TP.

        Delegates to PositionModifier.

        Args:
            ticket: Position ticket
            sl: New stop loss (None to keep current)
            tp: New take profit (None to keep current)

        Returns:
            True if successful
            False if failed (permanent error)
            "RETRY" if temporarily blocked by server (should retry later)
        """
        return self.position_modifier.modify_position(ticket, sl, tp)

    def close_position(self, ticket: int) -> bool:
        """
        Close a position.

        Delegates to PositionModifier.

        Args:
            ticket: Position ticket

        Returns:
            True if successful, False otherwise
        """
        return self.position_modifier.close_position(ticket)

