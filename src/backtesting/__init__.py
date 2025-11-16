"""
Backtesting package for multi-strategy trading bot.

This package provides a custom backtesting engine that:
- Simulates the exact live trading architecture
- Uses SimulatedBroker to replay historical data
- Runs the same strategies as live trading without modification
- Supports concurrent multi-symbol, multi-strategy backtesting
- Provides realistic position limit and risk management simulation

Structure:
- engine/: Custom backtesting engine (SimulatedBroker, BacktestController, etc.)
- metrics/: Performance metrics and analysis
- visualization/: Results visualization tools

Usage:
    See examples/test_custom_backtest_engine.py for complete example
    See docs/CUSTOM_BACKTEST_ENGINE.md for detailed documentation
"""

from .engine import (
    SimulatedBroker,
    SimulatedSymbolInfo,
    TimeController,
    TimeMode,
    BacktestController,
    BacktestDataLoader,
    ResultsAnalyzer
)

__version__ = "1.0.0"

__all__ = [
    'SimulatedBroker',
    'SimulatedSymbolInfo',
    'TimeController',
    'TimeMode',
    'BacktestController',
    'BacktestDataLoader',
    'ResultsAnalyzer'
]

