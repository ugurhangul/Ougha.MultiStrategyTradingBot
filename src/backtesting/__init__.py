"""
Backtesting package for multi-strategy trading bot.

This package provides backtesting capabilities using backtesting.py library:
- Data loading from MT5 or CSV
- Strategy adapters for backtesting.py
- Interactive Jupyter notebook backtesting
- Performance metrics and visualization
- Parameter optimization

Structure:
- data/: Data loading utilities
- adapters/: Strategy adapters for backtesting.py
- metrics/: Performance metrics and analysis
- visualization/: Results visualization tools
"""

from .data import BacktestingPyDataLoader
from .adapters import BacktestingPyStrategyAdapter, FakeoutStrategyAdapter

__version__ = "0.2.0"

__all__ = ['BacktestingPyDataLoader', 'BacktestingPyStrategyAdapter', 'FakeoutStrategyAdapter']

