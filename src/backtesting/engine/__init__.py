"""
Backtesting engine and execution simulator.

This module provides:
- Multi-strategy backtest engine
- Order execution simulator with slippage
- Position management for backtesting
- Event-driven backtesting framework
"""

from .backtest_engine import BacktestEngine, BacktestConfig

__all__ = ['BacktestEngine', 'BacktestConfig']

