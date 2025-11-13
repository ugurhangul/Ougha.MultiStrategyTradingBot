"""
Data models for the trading system.

This package contains domain-specific data models and enums
organized by responsibility for better maintainability.

Ported from MQL5 structures in FMS_Config.mqh and FMS_GlobalVars.mqh
"""

# Re-export all models and enums for convenient imports
from src.models.models.enums import SymbolCategory, PositionType
from src.models.models.symbol_models import SymbolParameters, SymbolStats
from src.models.models.position_models import PositionInfo
from src.models.models.candle_models import CandleData, ReferenceCandle
from src.models.models.range_models import RangeConfig
from src.models.models.breakout_models import UnifiedBreakoutState, MultiRangeBreakoutState
from src.models.models.filter_models import AdaptiveFilterState
from src.models.models.signal_models import TradeSignal

__all__ = [
    # Enums
    'SymbolCategory',
    'PositionType',
    
    # Symbol Models
    'SymbolParameters',
    'SymbolStats',
    
    # Position Models
    'PositionInfo',
    
    # Candle Models
    'CandleData',
    'ReferenceCandle',
    
    # Range Models
    'RangeConfig',
    
    # Breakout Models
    'UnifiedBreakoutState',
    'MultiRangeBreakoutState',
    
    # Filter Models
    'AdaptiveFilterState',
    
    # Signal Models
    'TradeSignal',
]

