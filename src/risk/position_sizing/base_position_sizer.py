"""
Base Position Sizer Interface

Abstract base class for all position sizing plugins.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class PositionSizeResult:
    """Result of position size calculation"""
    lot_size: float
    reason: str
    metadata: Dict[str, Any]


class BasePositionSizer(ABC):
    """
    Abstract base class for position sizing strategies.
    
    Position sizers determine the lot size for each trade based on:
    - Risk management rules
    - Account balance
    - Previous trade results
    - Strategy-specific logic
    
    All position sizers must implement this interface.
    """
    
    def __init__(self, symbol: str, **kwargs):
        """
        Initialize position sizer.
        
        Args:
            symbol: Trading symbol
            **kwargs: Additional configuration parameters
        """
        self.symbol = symbol
        self.is_initialized = False
    
    @abstractmethod
    def initialize(self, initial_lot_size: float) -> bool:
        """
        Initialize the position sizer with the base lot size.
        
        Args:
            initial_lot_size: Base lot size calculated by risk manager
            
        Returns:
            True if initialization successful
        """
        pass
    
    @abstractmethod
    def calculate_lot_size(self) -> float:
        """
        Calculate the lot size for the next trade.
        
        Returns:
            Lot size to use for next trade
        """
        pass
    
    @abstractmethod
    def on_trade_closed(self, profit: float, lot_size: float) -> None:
        """
        Update position sizer state after a trade closes.
        
        Args:
            profit: Trade profit/loss in account currency
            lot_size: Lot size of the closed trade
        """
        pass
    
    @abstractmethod
    def reset(self) -> None:
        """
        Reset position sizer to initial state.
        """
        pass
    
    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """
        Get current state of the position sizer.
        
        Returns:
            Dictionary containing current state
        """
        pass
    
    @abstractmethod
    def is_enabled(self) -> bool:
        """
        Check if position sizer is enabled and can calculate lot sizes.
        
        Returns:
            True if enabled, False if disabled (e.g., due to loss limits)
        """
        pass
    
    def get_name(self) -> str:
        """
        Get the name of this position sizer.
        
        Returns:
            Position sizer name
        """
        return self.__class__.__name__
    
    def shutdown(self) -> None:
        """
        Cleanup and shutdown the position sizer.
        Override if cleanup is needed.
        """
        pass

