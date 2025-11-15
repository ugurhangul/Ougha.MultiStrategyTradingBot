"""
Data loading utilities for backtesting.

This module provides tools to:
- Load historical data from MT5
- Load data from CSV files
- Convert data to pandas DataFrame format for backtesting.py
- Handle OHLCV data formatting
"""

from .backtesting_py_data_loader import BacktestingPyDataLoader

__all__ = ['BacktestingPyDataLoader']

