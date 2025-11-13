"""
Symbol Category Detection Service

Handles detection of symbol categories using MT5 native categories
and pattern matching as fallback.

This service follows the Single Responsibility Principle (SRP) by
focusing solely on category detection logic.
"""
from typing import Optional, Dict, List
from src.models.data_models import SymbolCategory


class SymbolCategoryDetector:
    """
    Service for detecting symbol categories.
    
    Uses a hybrid approach:
    1. PRIMARY: MT5 native category from symbol_info().category
    2. FALLBACK: Pattern matching on symbol name
    """
    
    # MT5 native category to SymbolCategory mapping
    # This is the PRIMARY categorization method when MT5 data is available
    MT5_CATEGORY_MAPPING: Dict[str, SymbolCategory] = {
        'Majors': SymbolCategory.MAJOR_FOREX,
        'Minors': SymbolCategory.MINOR_FOREX,
        'Exotic': SymbolCategory.EXOTIC_FOREX,
        'Metals': SymbolCategory.METALS,
        'Indices': SymbolCategory.INDICES,
        'Crypto': SymbolCategory.CRYPTO,
        'Energies': SymbolCategory.COMMODITIES,
        'Stocks': SymbolCategory.STOCKS,
        # Note: 'Other', 'Heartbeat' are not mapped and will fall through to pattern matching
    }

    # Symbol category detection patterns (FALLBACK method when MT5 category is unavailable)
    CATEGORY_PATTERNS: Dict[SymbolCategory, List[str]] = {
        SymbolCategory.MAJOR_FOREX: [
            'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF',
            'AUDUSD', 'USDCAD', 'NZDUSD'
        ],
        SymbolCategory.MINOR_FOREX: [
            'EURGBP', 'EURJPY', 'GBPJPY', 'EURCHF',
            'EURAUD', 'EURCAD', 'GBPCHF', 'GBPAUD',
            'AUDNZD', 'AUDCAD', 'AUDJPY', 'CADJPY',
            'CHFJPY', 'NZDJPY', 'EURNZD', 'GBPCAD',
            'GBPNZD', 'NZDCAD', 'NZDCHF'
        ],
        SymbolCategory.EXOTIC_FOREX: [
            'TRY', 'ZAR', 'MXN', 'BRL', 'RUB', 'HKD',
            'SGD', 'THB', 'NOK', 'SEK', 'DKK', 'PLN',
            'CZK', 'HUF', 'ILS', 'CNH'
        ],
        SymbolCategory.METALS: [
            'XAUUSD', 'GOLD', 'XAGUSD', 'SILVER', 'XAU', 'XAG',
            'XALUSD', 'XCUUSD', 'XPBUSD', 'XPDUSD', 'XPTUSD', 'XZNUSD'
        ],
        SymbolCategory.INDICES: [
            'SPX', 'SP500', 'US500', 'NAS100', 'NASDAQ', 'USTEC', 'US30', 'DOW',
            'DAX', 'DE30', 'GER', 'FTSE', 'UK100', 'CAC', 'FR40', 'FRA',
            'NIKKEI', 'JP225', 'JPN', 'ASX', 'AUS', 'HK50', 'DXY'
        ],
        SymbolCategory.CRYPTO: [
            'BTC', 'ETH', 'XRP', 'LTC', 'BCH', 'ADA',
            'DOT', 'LINK', 'DOGE', 'CRYPTO', 'BNB', 'SOL',
            'UNI', 'FIL', 'BAT', 'XTZ'
        ],
        SymbolCategory.COMMODITIES: [
            'WTI', 'BRENT', 'OIL', 'USOIL', 'UKOIL', 'NGAS', 'GAS', 'XNG'
        ]
    }
    
    @classmethod
    def detect_category(cls, symbol: str, mt5_category: Optional[str] = None) -> SymbolCategory:
        """
        Detect symbol category, preferring MT5 native category if available.

        This method uses a hybrid approach:
        1. PRIMARY: Use MT5 native category from symbol_info().category if provided
        2. FALLBACK: Use pattern matching on symbol name if MT5 category is unavailable

        Args:
            symbol: Symbol name (e.g., 'EURUSD', 'XAUUSD')
            mt5_category: Optional MT5 native category string (e.g., 'Majors', 'Crypto', 'Exotic')
                         from mt5.symbol_info(symbol).category

        Returns:
            SymbolCategory enum value
        """
        # PRIMARY: Try MT5 native category first if provided
        if mt5_category:
            mapped_category = cls.MT5_CATEGORY_MAPPING.get(mt5_category)
            if mapped_category:
                return mapped_category

        # FALLBACK: Use pattern matching on symbol name
        symbol_upper = symbol.upper()

        for category, patterns in cls.CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if pattern in symbol_upper:
                    return category

        return SymbolCategory.UNKNOWN
    
    @classmethod
    def get_category_name(cls, category: SymbolCategory) -> str:
        """
        Get human-readable category name.
        
        Args:
            category: Symbol category enum
            
        Returns:
            Human-readable category name
        """
        names = {
            SymbolCategory.MAJOR_FOREX: "Major Forex",
            SymbolCategory.MINOR_FOREX: "Minor Forex",
            SymbolCategory.EXOTIC_FOREX: "Exotic Forex",
            SymbolCategory.METALS: "Precious Metals",
            SymbolCategory.INDICES: "Stock Indices",
            SymbolCategory.CRYPTO: "Cryptocurrencies",
            SymbolCategory.COMMODITIES: "Commodities",
            SymbolCategory.STOCKS: "Stocks",
            SymbolCategory.UNKNOWN: "Unknown"
        }
        return names.get(category, "Unknown")

