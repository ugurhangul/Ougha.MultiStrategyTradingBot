"""
Symbol-specific optimization and categorization.

This package contains utilities for:
- Detecting symbol categories (Major Forex, Crypto, etc.)
- Storing optimized parameters for each category
- Providing a facade for easy parameter retrieval
"""

# Re-export all symbol-related classes
from src.config.symbols.category_detector import SymbolCategoryDetector
from src.config.symbols.parameters_repository import SymbolParametersRepository
from src.config.symbols.optimizer import SymbolOptimizer

__all__ = [
    'SymbolCategoryDetector',
    'SymbolParametersRepository',
    'SymbolOptimizer',
]

