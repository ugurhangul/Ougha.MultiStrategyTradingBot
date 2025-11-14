"""
Backtesting package for multi-strategy trading bot.

This package provides backtesting capabilities using hftbacktest library:
- MT5 data export and conversion
- Strategy adapters for backtesting
- Multi-strategy backtest engine
- Performance metrics and analysis
- Results visualization

Structure:
- data/: Data export and conversion utilities
- adapters/: Strategy adapters for backtesting
- engine/: Backtesting engine and execution simulator
- metrics/: Performance metrics and analysis
- visualization/: Results visualization tools
"""

from .data import MT5DataExporter

__version__ = "0.1.0"

__all__ = ['MT5DataExporter']

