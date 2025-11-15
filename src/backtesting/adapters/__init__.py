"""
Strategy adapters for backtesting.py.

This module provides adapters to make live trading strategies
compatible with the backtesting.py library:
- Base strategy adapter for backtesting.py
- Fakeout strategy adapter
"""

from .backtesting_py_strategy_adapter import (
    BacktestingPyStrategyAdapter,
    FakeoutStrategyAdapter
)

__all__ = [
    'BacktestingPyStrategyAdapter',
    'FakeoutStrategyAdapter',
]

