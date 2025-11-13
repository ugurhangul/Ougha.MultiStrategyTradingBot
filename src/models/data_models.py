"""
Data models for the trading system.
Ported from MQL5 structures in FMS_Config.mqh and FMS_GlobalVars.mqh

This module re-exports all models from the models package for backward compatibility.
"""

# Import all models and enums from the models package
from src.models.models import (
    # Enums
    SymbolCategory,
    PositionType,

    # Symbol Models
    SymbolParameters,
    SymbolStats,

    # Position Models
    PositionInfo,

    # Candle Models
    CandleData,
    ReferenceCandle,

    # Range Models
    RangeConfig,

    # Breakout Models
    UnifiedBreakoutState,
    MultiRangeBreakoutState,

    # Filter Models
    AdaptiveFilterState,

    # Signal Models
    TradeSignal,
)

# Re-export all for backward compatibility
__all__ = [
    'SymbolCategory',
    'PositionType',
    'SymbolParameters',
    'SymbolStats',
    'PositionInfo',
    'CandleData',
    'ReferenceCandle',
    'RangeConfig',
    'UnifiedBreakoutState',
    'MultiRangeBreakoutState',
    'AdaptiveFilterState',
    'TradeSignal',
]

