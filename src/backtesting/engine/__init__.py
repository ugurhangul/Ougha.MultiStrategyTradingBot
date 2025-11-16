"""
Custom Backtesting Engine.

Multi-symbol, multi-strategy concurrent backtesting engine that accurately
simulates the TradingController's concurrent execution architecture.
"""

from src.backtesting.engine.simulated_broker import SimulatedBroker, SimulatedSymbolInfo
from src.backtesting.engine.time_controller import TimeController, TimeMode
from src.backtesting.engine.backtest_controller import BacktestController
from src.backtesting.engine.data_loader import BacktestDataLoader
from src.backtesting.engine.results_analyzer import ResultsAnalyzer

__all__ = [
    'SimulatedBroker',
    'SimulatedSymbolInfo',
    'TimeController',
    'TimeMode',
    'BacktestController',
    'BacktestDataLoader',
    'ResultsAnalyzer',
]

