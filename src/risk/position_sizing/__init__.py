"""
Position Sizing Plugin System

Provides pluggable position sizing strategies that can be used by any trading strategy.
"""

from src.risk.position_sizing.base_position_sizer import BasePositionSizer
from src.risk.position_sizing.position_sizer_factory import (
    PositionSizerRegistry,
    register_position_sizer,
    create_position_sizer
)
from src.risk.position_sizing.fixed_position_sizer import FixedPositionSizer
from src.risk.position_sizing.martingale_position_sizer import MartingalePositionSizer
from src.risk.position_sizing.pattern_based_position_sizer import PatternBasedPositionSizer

__all__ = [
    'BasePositionSizer',
    'PositionSizerRegistry',
    'register_position_sizer',
    'create_position_sizer',
    'FixedPositionSizer',
    'MartingalePositionSizer',
    'PatternBasedPositionSizer',
]

