"""Strategy components"""

# Import all strategy modules to trigger @register_strategy decorator registration
# This ensures strategies are registered in the StrategyRegistry before they're needed
from src.strategy.true_breakout_strategy import TrueBreakoutStrategy
from src.strategy.fakeout_strategy import FakeoutStrategy
from src.strategy.hft_momentum_strategy import HFTMomentumStrategy

__all__ = [
    'TrueBreakoutStrategy',
    'FakeoutStrategy',
    'HFTMomentumStrategy',
]
