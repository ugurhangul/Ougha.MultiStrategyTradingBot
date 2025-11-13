"""
Order execution and management.
Ported from FMS_TradeExecution.mqh

This module re-exports all order management components from the order_management package
for backward compatibility.
"""

# Import all order management components from the order_management package
from src.execution.order_management import (
    OrderExecutor,
    PositionModifier,
    StopValidator,
    MarketChecker,
    OrderManager,
)

# Re-export all for backward compatibility
__all__ = [
    'OrderExecutor',
    'PositionModifier',
    'StopValidator',
    'MarketChecker',
    'OrderManager',
]

