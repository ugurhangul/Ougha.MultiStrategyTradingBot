"""
Trade signal models.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from src.models.models.enums import PositionType

# Strategy type code constants (imported from constants to avoid circular dependency)
STRATEGY_TYPE_FALSE_BREAKOUT: Final[str] = "FB"
STRATEGY_TYPE_TRUE_BREAKOUT: Final[str] = "TB"
STRATEGY_TYPE_HFT_MOMENTUM: Final[str] = "HFT"


@dataclass
class TradeSignal:
    """Trade signal information"""
    symbol: str
    signal_type: PositionType
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    timestamp: datetime
    reason: str = ""
    max_spread_percent: float = 0.1  # Maximum allowed spread as percentage of price (e.g., 0.1 = 0.1%)
    comment: str = ""

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward(self) -> float:
        return abs(self.take_profit - self.entry_price)

    @property
    def risk_reward_ratio(self) -> float:
        if self.risk == 0:
            return 0.0
        return self.reward / self.risk



