"""
Symbol category utilities.

Provides utilities for symbol categorization using hybrid approach.
"""
from typing import Optional

from src.models.data_models import SymbolCategory
from src.config.symbols import SymbolCategoryDetector


class SymbolCategoryUtils:
    """Utilities for symbol categorization"""
    
    @staticmethod
    def detect_category(symbol: str, mt5_category: Optional[str] = None) -> SymbolCategory:
        """
        Detect symbol category using hybrid approach.
        
        Args:
            symbol: Symbol name
            mt5_category: Optional MT5 native category
            
        Returns:
            SymbolCategory enum
        """
        return SymbolCategoryDetector.detect_category(symbol, mt5_category)
    
    @staticmethod
    def get_category_name(category: SymbolCategory) -> str:
        """Get human-readable category name"""
        return SymbolCategoryDetector.get_category_name(category)

