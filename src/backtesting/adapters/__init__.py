"""
Strategy adapters for backtesting.

This module provides adapters to make live trading strategies
compatible with the backtesting engine:
- Base strategy adapter interface
- True Breakout strategy adapter
- Fakeout strategy adapter
- HFT Momentum strategy adapter
"""

from .base_strategy_adapter import (
    BaseStrategyAdapter,
    BacktestOrder,
    BacktestPosition
)
from .fakeout_strategy_adapter import FakeoutStrategyAdapter
from .true_breakout_strategy_adapter import TrueBreakoutStrategyAdapter
from .hft_momentum_strategy_adapter import HFTMomentumStrategyAdapter

__all__ = [
    'BaseStrategyAdapter',
    'BacktestOrder',
    'BacktestPosition',
    'FakeoutStrategyAdapter',
    'TrueBreakoutStrategyAdapter',
    'HFTMomentumStrategyAdapter',
]

