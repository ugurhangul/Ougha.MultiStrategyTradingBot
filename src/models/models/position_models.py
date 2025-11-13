"""
Position-related data models.
"""
from dataclasses import dataclass
from datetime import datetime
from src.models.models.enums import PositionType


@dataclass
class PositionInfo:
    """Position information structure"""
    ticket: int
    symbol: str
    position_type: PositionType
    volume: float
    open_price: float
    current_price: float
    sl: float
    tp: float
    profit: float
    open_time: datetime
    magic_number: int
    comment: str = ""
    
    @property
    def risk(self) -> float:
        """Calculate risk (distance from entry to SL)"""
        return abs(self.open_price - self.sl)
    
    @property
    def current_pnl(self) -> float:
        """Calculate current P&L in price terms"""
        if self.position_type == PositionType.BUY:
            return self.current_price - self.open_price
        else:
            return self.open_price - self.current_price
    
    @property
    def current_rr(self) -> float:
        """Calculate current risk/reward ratio"""
        if self.risk == 0:
            return 0.0
        return self.current_pnl / self.risk

