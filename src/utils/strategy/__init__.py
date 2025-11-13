"""
Strategy utilities package.

This package provides shared utilities for trading strategies:
- Symbol categorization
- Stop loss calculation
- ATR-based parameter optimization
- Volume/spread/momentum validation helpers
- Breakout and range detection
- Continuation and retest validation
- Divergence detection
- Trade management utilities

This module follows the DRY principle by extracting common logic
from individual strategies into reusable components.
"""

# Re-export all classes for convenient imports
from src.utils.strategy.category_utils import SymbolCategoryUtils
from src.utils.strategy.risk_parameters import (
    StopLossParameters,
    ValidationThresholds,
    StopLossCalculator,
    ValidationThresholdsCalculator
)
from src.utils.strategy.signal_validation import SignalValidationHelpers
from src.utils.strategy.breakout_detection import RangeDetector, BreakoutDetector
from src.utils.strategy.continuation_validation import ContinuationValidator
from src.utils.strategy.divergence_detection import DivergenceDetector
from src.utils.strategy.trade_management import TradeManagementHelper

__all__ = [
    # Category utilities
    'SymbolCategoryUtils',
    
    # Risk parameters
    'StopLossParameters',
    'ValidationThresholds',
    'StopLossCalculator',
    'ValidationThresholdsCalculator',
    
    # Signal validation
    'SignalValidationHelpers',
    
    # Breakout detection
    'RangeDetector',
    'BreakoutDetector',
    
    # Continuation validation
    'ContinuationValidator',
    
    # Divergence detection
    'DivergenceDetector',
    
    # Trade management
    'TradeManagementHelper',
]

