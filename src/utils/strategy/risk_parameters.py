"""
Risk parameters and calculations.

Provides stop loss parameters, validation thresholds, and calculators
for category-based risk management.
"""
from typing import Optional, Dict
from dataclasses import dataclass

from src.models.data_models import SymbolCategory, SymbolParameters
from src.config.symbols.parameters_repository import SymbolParametersRepository


@dataclass
class StopLossParameters:
    """Category-based stop loss parameters"""
    category_name: str
    base_stop_loss_points: int
    atr_multiplier: float


@dataclass
class ValidationThresholds:
    """Symbol category-based validation thresholds"""
    min_momentum_strength: float
    min_volume_multiplier: float
    min_atr_multiplier: float
    max_atr_multiplier: float
    trend_ema_period: int
    max_spread_multiplier: float


class StopLossCalculator:
    """Utilities for stop loss calculation"""

    @classmethod
    def get_stop_loss_params(cls, category: SymbolCategory) -> StopLossParameters:
        """
        Get stop loss parameters for a symbol category.

        Args:
            category: Symbol category

        Returns:
            StopLossParameters for the category
        """
        # Get parameters from centralized repository
        default_params = SymbolParameters()
        params = SymbolParametersRepository.get_parameters(category, default_params)

        # Map category to display name
        category_names = {
            SymbolCategory.MAJOR_FOREX: "Forex Major",
            SymbolCategory.MINOR_FOREX: "Forex Cross",
            SymbolCategory.EXOTIC_FOREX: "Forex Exotic",
            SymbolCategory.METALS: "Metals",
            SymbolCategory.INDICES: "Indices",
            SymbolCategory.CRYPTO: "Crypto",
            SymbolCategory.COMMODITIES: "Commodities",
            SymbolCategory.STOCKS: "Stocks",
            SymbolCategory.UNKNOWN: "Unknown"
        }

        return StopLossParameters(
            category_name=category_names.get(category, "Unknown"),
            base_stop_loss_points=params.base_stop_loss_points,
            atr_multiplier=params.atr_multiplier_for_sl
        )
    
    @classmethod
    def calculate_dynamic_stop_loss(cls, category: SymbolCategory, 
                                    current_atr: Optional[float] = None,
                                    point: float = 0.0001,
                                    use_atr: bool = True,
                                    custom_atr_multiplier: Optional[float] = None) -> int:
        """
        Calculate dynamic stop loss in points based on category and ATR.
        
        Args:
            category: Symbol category
            current_atr: Current ATR value (optional)
            point: Symbol point size
            use_atr: Whether to use ATR adjustment
            custom_atr_multiplier: Custom ATR multiplier (overrides category default)
            
        Returns:
            Stop loss distance in points
        """
        params = cls.get_stop_loss_params(category)
        calculated_sl = params.base_stop_loss_points
        
        # Apply ATR multiplier if enabled and ATR is available
        if use_atr and current_atr is not None and current_atr > 0 and point > 0:
            atr_multiplier = custom_atr_multiplier if custom_atr_multiplier else params.atr_multiplier
            atr_based_sl = int(round((current_atr * atr_multiplier) / point))
            
            # Use the larger of base SL or ATR-based SL
            calculated_sl = max(calculated_sl, atr_based_sl)
        
        return calculated_sl


class ValidationThresholdsCalculator:
    """Utilities for calculating validation thresholds based on symbol category"""

    @classmethod
    def get_thresholds(cls, category: SymbolCategory) -> ValidationThresholds:
        """
        Get validation thresholds for a symbol category.

        Args:
            category: Symbol category

        Returns:
            ValidationThresholds for the category
        """
        # Get parameters from centralized repository
        default_params = SymbolParameters()
        params = SymbolParametersRepository.get_parameters(category, default_params)

        return ValidationThresholds(
            min_momentum_strength=params.min_momentum_strength,
            min_volume_multiplier=params.min_volume_multiplier,
            min_atr_multiplier=params.min_atr_multiplier,
            max_atr_multiplier=params.max_atr_multiplier,
            trend_ema_period=params.trend_ema_period,
            max_spread_multiplier=params.max_spread_multiplier
        )

    @classmethod
    def calculate_momentum_threshold(cls, category: SymbolCategory,
                                     avg_spread: float, point: float) -> float:
        """
        Calculate minimum momentum strength threshold.

        Args:
            category: Symbol category
            avg_spread: Average spread in price units
            point: Symbol point size

        Returns:
            Minimum momentum strength in price units
        """
        thresholds = cls.get_thresholds(category)
        return thresholds.min_momentum_strength * avg_spread * point

