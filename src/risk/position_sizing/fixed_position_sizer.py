"""
Fixed Position Sizer

Standard position sizing that uses a fixed lot size based on risk percentage.
This is the default position sizing strategy used by most trading systems.
"""

from typing import Dict, Any

from src.risk.position_sizing.base_position_sizer import BasePositionSizer
from src.risk.position_sizing.position_sizer_factory import register_position_sizer
from src.utils.logger import get_logger


@register_position_sizer(
    "fixed",
    description="Fixed lot size based on risk percentage",
    default=True
)
class FixedPositionSizer(BasePositionSizer):
    """
    Fixed position sizing strategy.
    
    Always returns the same lot size (calculated by risk manager based on
    risk percentage and stop loss distance). This is the standard approach
    used by most trading systems.
    
    Features:
    - Consistent risk per trade
    - No progression or scaling
    - Simple and predictable
    """
    
    def __init__(self, symbol: str, **kwargs):
        """
        Initialize fixed position sizer.
        
        Args:
            symbol: Trading symbol
            **kwargs: Additional parameters (unused)
        """
        super().__init__(symbol, **kwargs)
        self.logger = get_logger()
        
        self.initial_lot_size: float = 0.0
        self.current_lot_size: float = 0.0
        
        # Statistics
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
    
    def initialize(self, initial_lot_size: float) -> bool:
        """
        Initialize with base lot size.
        
        Args:
            initial_lot_size: Base lot size from risk manager
            
        Returns:
            True if successful
        """
        self.initial_lot_size = initial_lot_size
        self.current_lot_size = initial_lot_size
        self.is_initialized = True
        
        self.logger.info(
            f"Fixed position sizer initialized for {self.symbol}: {initial_lot_size:.2f} lots",
            self.symbol
        )
        
        return True
    
    def calculate_lot_size(self) -> float:
        """
        Calculate lot size (always returns fixed size).
        
        Returns:
            Fixed lot size
        """
        return self.current_lot_size
    
    def on_trade_closed(self, profit: float, lot_size: float) -> None:
        """
        Update statistics after trade closure.
        
        Args:
            profit: Trade profit/loss
            lot_size: Lot size of closed trade
        """
        self.total_trades += 1
        
        if profit > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        # Lot size remains unchanged in fixed sizing
        self.logger.debug(
            f"Trade closed: {'WIN' if profit > 0 else 'LOSS'} ${profit:.2f} | "
            f"Lot size remains: {self.current_lot_size:.2f}",
            self.symbol
        )
    
    def reset(self) -> None:
        """
        Reset to initial state.
        """
        self.current_lot_size = self.initial_lot_size
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        self.logger.info(f"Fixed position sizer reset for {self.symbol}", self.symbol)
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get current state.
        
        Returns:
            State dictionary
        """
        return {
            'type': 'fixed',
            'symbol': self.symbol,
            'is_initialized': self.is_initialized,
            'initial_lot_size': self.initial_lot_size,
            'current_lot_size': self.current_lot_size,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        }
    
    def is_enabled(self) -> bool:
        """
        Check if position sizer is enabled.
        
        Returns:
            Always True for fixed sizing
        """
        return self.is_initialized

