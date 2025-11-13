"""
Symbol-specific optimization.
Ported from FMS_SymbolOptimization.mqh

This module now acts as a facade coordinating SymbolCategoryDetector
and SymbolParametersRepository services, following SOLID principles.
"""
from typing import Optional
from src.models.data_models import SymbolCategory, SymbolParameters
from src.config.symbols.category_detector import SymbolCategoryDetector
from src.config.symbols.parameters_repository import SymbolParametersRepository


class SymbolOptimizer:
    """
    Facade for symbol-specific parameter optimization.
    
    Coordinates SymbolCategoryDetector and SymbolParametersRepository
    to provide a simple interface for getting symbol parameters.
    """
    
    # Expose constants from services for backward compatibility
    MT5_CATEGORY_MAPPING = SymbolCategoryDetector.MT5_CATEGORY_MAPPING
    CATEGORY_PATTERNS = SymbolCategoryDetector.CATEGORY_PATTERNS
    CATEGORY_PARAMETERS = SymbolParametersRepository.CATEGORY_PARAMETERS
    
    @classmethod
    def detect_category(cls, symbol: str, mt5_category: Optional[str] = None) -> SymbolCategory:
        """
        Detect symbol category - delegates to SymbolCategoryDetector.
        
        Args:
            symbol: Symbol name (e.g., 'EURUSD', 'XAUUSD')
            mt5_category: Optional MT5 native category string
            
        Returns:
            SymbolCategory enum value
        """
        return SymbolCategoryDetector.detect_category(symbol, mt5_category)
    
    @classmethod
    def get_category_name(cls, category: SymbolCategory) -> str:
        """
        Get human-readable category name - delegates to SymbolCategoryDetector.
        
        Args:
            category: Symbol category enum
            
        Returns:
            Human-readable category name
        """
        return SymbolCategoryDetector.get_category_name(category)
    
    @classmethod
    def get_parameters(cls, category: SymbolCategory, default_params: SymbolParameters) -> SymbolParameters:
        """
        Get optimized parameters for symbol category - delegates to SymbolParametersRepository.
        
        Args:
            category: Symbol category
            default_params: Default parameters to use if category is unknown
            
        Returns:
            SymbolParameters for the category
        """
        return SymbolParametersRepository.get_parameters(category, default_params)
    
    @classmethod
    def get_symbol_parameters(cls, symbol: str, default_params: SymbolParameters,
                             mt5_category: Optional[str] = None) -> tuple[SymbolCategory, SymbolParameters]:
        """
        Get category and optimized parameters for a symbol.
        
        Args:
            symbol: Symbol name
            default_params: Default parameters
            mt5_category: Optional MT5 native category from symbol_info().category
            
        Returns:
            Tuple of (category, parameters)
        """
        category = cls.detect_category(symbol, mt5_category)
        params = cls.get_parameters(category, default_params)
        return category, params

