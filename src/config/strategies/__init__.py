"""
Strategy-specific configuration classes.

This package contains configuration dataclasses for individual trading strategies.
Each strategy has its own configuration file with parameters specific to that strategy.
"""

# Re-export all strategy configuration classes
from src.config.strategies.martingale_types import MartingaleType
from src.config.strategies.breakout_config import BreakoutStrategyConfig
from src.config.strategies.true_breakout_config import TrueBreakoutConfig
from src.config.strategies.fakeout_config import FakeoutConfig

__all__ = [
    'MartingaleType',
    'BreakoutStrategyConfig',
    'TrueBreakoutConfig',
    'FakeoutConfig',
]

